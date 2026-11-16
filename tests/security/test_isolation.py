import json
import os
import socket
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from runner.config import RunnerSettings
from runner.isolation import MEMORY, PIDS, GVisor, IsolationUnavailable, check_cgroup, check_daemon
from runner.watchdog import reap

IMAGE = "sha256:" + "a" * 64


def daemon():
    return {
        "Runtimes": {"runsc": {"path": "/usr/local/bin/runsc", "runtimeArgs": ["--platform=systrap"]}},
        "SecurityOptions": ["name=seccomp,profile=builtin"],
        "CgroupVersion": "2",
        "CgroupDriver": "systemd",
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(Runtimes={}),
        lambda d: d["Runtimes"]["runsc"].update(path="/usr/bin/runc"),
        lambda d: d["Runtimes"]["runsc"].update(runtimeArgs=["--ignore-cgroups"]),
        lambda d: d.update(SecurityOptions=["name=rootless"]),
        lambda d: d.update(CgroupVersion="1"),
        lambda d: d.update(CgroupDriver=""),
    ],
)
def test_unsafe_daemons_rejected(change):
    value = daemon()
    change(value)
    with pytest.raises(IsolationUnavailable):
        check_daemon(value)


def test_no_runtime_fallback():
    check_daemon(daemon())


@pytest.fixture
def cgroup(tmp_path):
    root, proc = tmp_path / "cgroups", tmp_path / "proc"
    group = root / "job"
    group.mkdir(parents=True)
    (proc / "42").mkdir(parents=True)
    (proc / "42" / "cgroup").write_text("0::/job\n")
    for name, value in {
        "memory.max": str(MEMORY),
        "memory.swap.max": "0",
        "pids.max": str(PIDS),
        "cpu.max": "100000 100000",
    }.items():
        (group / name).write_text(value)
    return root, proc, group


def test_actual_kernel_cgroup_controls(cgroup):
    root, proc, _ = cgroup
    check_cgroup(42, root, proc)


@pytest.mark.parametrize(
    "control,value",
    [
        ("memory.max", "max"),
        ("memory.swap.max", "1"),
        ("pids.max", "max"),
        ("cpu.max", "max 100000"),
        ("cpu.max", "200000 100000"),
    ],
)
def test_ignored_resource_limits_fail_closed(cgroup, control, value):
    root, proc, group = cgroup
    (group / control).write_text(value)
    with pytest.raises(IsolationUnavailable):
        check_cgroup(42, root, proc)


class Stream:
    def __init__(self, data, events):
        self.data = bytearray(data)
        self.events = events
        self.sent = None

    def settimeout(self, _):
        pass

    def sendall(self, data):
        self.events.append("source_sent")
        self.sent = json.loads(data)

    def shutdown(self, _):
        pass

    def recv(self, size):
        part = bytes(self.data[:size])
        del self.data[:size]
        return part


def frame(data, stream=1):
    return bytes([stream, 0, 0, 0]) + len(data).to_bytes(4, "big") + data


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    events = []
    host = {
        "Runtime": "runsc",
        "NetworkMode": "none",
        "ReadonlyRootfs": True,
        "Privileged": False,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges:true"],
        "LogConfig": {"Type": "none"},
        "Memory": MEMORY,
        "MemorySwap": MEMORY,
        "PidsLimit": PIDS,
        "NanoCpus": 1000000000,
        "IpcMode": "none",
        "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=8388608,mode=1777"},
    }
    container = MagicMock()
    container.attrs = {
        "HostConfig": host,
        "Config": {"User": "65532:65532", "Env": ["PATH=/usr/bin", "LANG=C.UTF-8"]},
        "Image": IMAGE,
        "Mounts": [],
        "State": {"Pid": 42, "OOMKilled": False},
    }
    container.wait.return_value = {"StatusCode": 0}
    client = MagicMock()
    client.containers.create.return_value = container
    stream = Stream(frame(b"5\n"), events)
    client.api.attach_socket.return_value = SimpleNamespace(_sock=stream, close=lambda: None)
    settings = RunnerSettings(
        token="test-only-token-value-at-least-32-chars", image=IMAGE, state_dir=tmp_path
    )
    engine = GVisor(client, settings)
    monkeypatch.setattr(engine, "watchdog_ready", lambda: events.append("watchdog_checked"))
    monkeypatch.setattr("runner.isolation.check_cgroup", lambda _: events.append("cgroups_verified"))
    return engine, container, client, stream, events


def test_source_sent_only_after_isolation_checks(sandbox):
    engine, container, client, stream, events = sandbox
    result = engine._execute({"mode": "run", "source": "print(5)", "stdin": ""})
    assert result.stdout == b"5\n" and result.reason is None
    assert events.index("cgroups_verified") < events.index("source_sent")
    kwargs = client.containers.create.call_args.kwargs
    assert kwargs["runtime"] == "runsc" and kwargs["network_mode"] == "none"
    assert kwargs["environment"] == {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
    assert "volumes" not in kwargs and "privileged" not in kwargs
    assert kwargs["use_config_proxy"] is False
    container.remove.assert_called_once_with(force=True)


@pytest.mark.parametrize("unsafe", ["runtime", "network", "mount", "secret", "privilege", "limits"])
def test_configuration_mismatch_never_sends_source(sandbox, unsafe):
    engine, container, _, stream, _ = sandbox
    if unsafe == "runtime":
        container.attrs["HostConfig"]["Runtime"] = "runc"
    if unsafe == "network":
        container.attrs["HostConfig"]["NetworkMode"] = "host"
    if unsafe == "mount":
        container.attrs["Mounts"] = [{"Source": "/host"}]
    if unsafe == "secret":
        container.attrs["Config"]["Env"].append("DATABASE_URL=private")
    if unsafe == "privilege":
        container.attrs["HostConfig"]["Privileged"] = True
    if unsafe == "limits":
        container.attrs["HostConfig"]["Memory"] = 0
    with pytest.raises(IsolationUnavailable):
        engine._execute({"source": "untrusted", "stdin": ""})
    assert stream.sent is None
    container.remove.assert_called_once()


@pytest.mark.parametrize("which", ["stdout", "stderr"])
def test_output_is_bounded_and_guest_destroyed(sandbox, which):
    engine, container, client, _, events = sandbox
    stream = Stream(frame(b"x" * 32769, 1 if which == "stdout" else 2), events)
    client.api.attach_socket.return_value = SimpleNamespace(_sock=stream, close=lambda: None)
    assert engine._execute({"source": "not executed by test", "stdin": ""}).reason == "output_limit"
    container.remove.assert_called_once()


def test_wall_timeout_always_cleans_up(sandbox):
    engine, container, _, stream, _ = sandbox

    def timeout(_):
        raise socket.timeout()

    stream.recv = timeout
    assert engine._execute({"source": "not executed by test", "stdin": ""}).reason == "time_limit"
    container.remove.assert_called_once()


def test_cleanup_failure_quarantines_controller(sandbox):
    engine, container, _, _, _ = sandbox
    container.remove.side_effect = RuntimeError("daemon unavailable")
    with pytest.raises(IsolationUnavailable):
        engine._execute({"source": "not executed by test", "stdin": ""})
    with pytest.raises(IsolationUnavailable, match="quarantined"):
        engine.verify()


def test_watchdog_stale_or_missing_fails_closed(tmp_path):
    settings = RunnerSettings(
        token="test-only-token-value-at-least-32-chars", image=IMAGE, state_dir=tmp_path
    )
    engine = GVisor(MagicMock(), settings)
    with pytest.raises(IsolationUnavailable):
        engine.watchdog_ready()
    (tmp_path / "watchdog.json").write_text(json.dumps({"pid": os.getpid(), "time": time.time() - 10}))
    with pytest.raises(IsolationUnavailable):
        engine.watchdog_ready()


def test_independent_reaper_only_removes_expired_owned_containers():
    expired, active = MagicMock(), MagicMock()
    expired.labels = {"org.codejudge.deadline": "1"}
    active.labels = {"org.codejudge.deadline": "102"}
    client = MagicMock()
    client.containers.list.return_value = [expired, active]
    reap(client, 100)
    expired.remove.assert_called_once_with(force=True)
    active.remove.assert_not_called()
    assert client.containers.list.call_args.kwargs["filters"] == {"label": "org.codejudge.job"}


def test_startup_timeout_never_becomes_a_fabricated_test_result(sandbox):
    engine, container, _, stream, _ = sandbox
    container.start.side_effect = socket.timeout()
    with pytest.raises(IsolationUnavailable, match="startup timed out"):
        engine._execute({"source": "not executed", "stdin": ""})
    assert stream.sent is None
    container.remove.assert_called_once()


@pytest.mark.parametrize(
    "exit_code,oom,reason",
    [(1, False, "runtime_error"), (152, False, "time_limit"), (137, True, "memory_limit")],
)
def test_correct_output_does_not_override_abnormal_exit(sandbox, exit_code, oom, reason):
    engine, container, _, _, _ = sandbox
    container.wait.return_value = {"StatusCode": exit_code}
    container.attrs["State"]["OOMKilled"] = oom
    outcome = engine._execute({"source": "not executed", "stdin": ""})
    assert outcome.stdout == b"5\n" and outcome.reason == reason


def test_missing_admission_prevents_even_probe_creation(sandbox, monkeypatch):
    engine, _, client, stream, _ = sandbox
    client.info.return_value = daemon()
    client.containers.list.return_value = []
    with pytest.raises(IsolationUnavailable, match="deployment security validation"):
        engine.verify()
    client.containers.create.assert_not_called()
    assert stream.sent is None


def test_verified_cache_never_bypasses_current_policy_checks(sandbox, monkeypatch):
    engine, _, client, _, _ = sandbox
    client.info.return_value = daemon()
    client.containers.list.return_value = []
    client.images.get.return_value = SimpleNamespace(
        id=IMAGE,
        attrs={
            "Config": {
                "Labels": {"org.codejudge.sandbox": "python-stdio-v1"},
                "Entrypoint": ["/usr/local/bin/python", "-I", "-S", "-B", "/opt/bootstrap.py"],
                "User": "65532:65532",
            }
        },
    )
    monkeypatch.setattr("runner.admission.check_admission", lambda *_: None)
    probe = MagicMock(
        return_value=SimpleNamespace(
            stdout=json.dumps(
                {
                    "uid": 65532,
                    "env_safe": True,
                    "limits": True,
                    "fork_denied": True,
                    "network_denied": True,
                    "root_readonly": True,
                }
            ),
            reason=None,
        )
    )
    monkeypatch.setattr(engine, "_execute", probe)
    engine.verify()
    engine.verify()
    probe.assert_called_once_with({"mode": "probe"})
    client.info.return_value["Runtimes"]["runsc"]["runtimeArgs"] = ["--ignore-cgroups"]
    with pytest.raises(IsolationUnavailable):
        engine.verify()


def test_stream_close_error_still_destroys_guest_and_quarantines(sandbox):
    engine, container, client, _, _ = sandbox
    client.api.attach_socket.return_value.close = MagicMock(side_effect=OSError("close failed"))
    with pytest.raises(IsolationUnavailable, match="stream cleanup failed"):
        engine._execute({"source": "not executed", "stdin": ""})
    container.remove.assert_called_once_with(force=True)
    assert engine.quarantined
