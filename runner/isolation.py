"""gVisor-only execution, with host cgroup verification before accepting any source."""

import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

MEMORY = 512 * 1024 * 1024  # Includes Sentry overhead; Python address space is separately capped at 128 MiB.
PIDS = 128  # Host runtime threads; guest RLIMIT_NPROC=1 prohibits child processes/threads.
WALL_SECONDS = 5
OUTPUT_BYTES = 32768
LABEL = "org.codejudge.job"


def process_birth(pid):
    # Field 22, after the parenthesized process name; prevents accepting a reused PID.
    return (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]


class IsolationUnavailable(Exception):
    pass


@dataclass
class Outcome:
    stdout: bytes
    reason: str | None
    duration_ms: int


def check_daemon(info):
    runtime = info.get("Runtimes", {}).get("runsc")
    if not runtime or Path(runtime.get("path", "")).name != "runsc":
        raise IsolationUnavailable("gVisor runsc is not configured")
    if any("rootless" in option for option in info.get("SecurityOptions", [])):
        raise IsolationUnavailable("rootless runtime has not been validated")
    args = runtime.get("runtimeArgs", [])
    if any(arg not in {"--platform=systrap", "--platform=kvm"} for arg in args):
        raise IsolationUnavailable("unapproved runsc flags (including ignored cgroups)")
    if info.get("CgroupVersion") != "2" or not info.get("CgroupDriver"):
        raise IsolationUnavailable("cgroup v2 is required")
    if not any("seccomp" in option for option in info.get("SecurityOptions", [])):
        raise IsolationUnavailable("host seccomp is required")


def check_cgroup(pid, root=Path("/sys/fs/cgroup"), proc=Path("/proc")):
    # Native controller on the same dedicated host, not a socket-mounted application container.
    lines = (proc / str(pid) / "cgroup").read_text().splitlines()
    unified = [line[3:] for line in lines if line.startswith("0::")]
    if len(unified) != 1 or ".." in Path(unified[0]).parts:
        raise IsolationUnavailable("cannot identify sandbox cgroup")
    group = (root / unified[0].lstrip("/")).resolve()
    if not group.is_relative_to(root.resolve()) or group == root.resolve():
        raise IsolationUnavailable("sandbox must have a dedicated cgroup")
    memory = (group / "memory.max").read_text().strip()
    swap = (group / "memory.swap.max").read_text().strip()
    pids = (group / "pids.max").read_text().strip()
    quota, period = (group / "cpu.max").read_text().split()
    if memory == "max" or not 0 < int(memory) <= MEMORY or swap != "0":
        raise IsolationUnavailable("memory or swap limit is not enforced")
    if pids == "max" or not 0 < int(pids) <= PIDS:
        raise IsolationUnavailable("host process limit is not enforced")
    if quota == "max" or int(quota) <= 0 or int(period) <= 0 or int(quota) > int(period):
        raise IsolationUnavailable("CPU quota is not enforced")


def check_container(container, image):
    data = container.attrs
    host, config = data["HostConfig"], data["Config"]
    if host.get("Runtime") != "runsc" or host.get("NetworkMode") != "none":
        raise IsolationUnavailable("runtime or network mismatch")
    if data.get("Image") != image or config.get("User") != "65532:65532":
        raise IsolationUnavailable("image or user mismatch")
    if not host.get("ReadonlyRootfs") or host.get("Privileged") or data.get("Mounts"):
        raise IsolationUnavailable("unsafe filesystem or privilege configuration")
    if host.get("Binds") or host.get("Devices") or host.get("DeviceRequests"):
        raise IsolationUnavailable("host resources exposed")
    if host.get("PidMode") or host.get("IpcMode") != "none":
        raise IsolationUnavailable("shared namespaces")
    if set(host.get("CapDrop", [])) != {"ALL"} or host.get("CapAdd"):
        raise IsolationUnavailable("capabilities are not dropped")
    if "no-new-privileges:true" not in host.get("SecurityOpt", []):
        raise IsolationUnavailable("no-new-privileges is required")
    if host.get("LogConfig", {}).get("Type") != "none":
        raise IsolationUnavailable("unbounded daemon logging is forbidden")
    if (
        host.get("Memory") != MEMORY
        or host.get("MemorySwap") != MEMORY
        or host.get("PidsLimit") != PIDS
        or host.get("NanoCpus") != 1000000000
    ):
        raise IsolationUnavailable("resource configuration mismatch")
    tmpfs = host.get("Tmpfs", {})
    if set(tmpfs) != {"/tmp"} or tmpfs["/tmp"] != "rw,noexec,nosuid,nodev,size=8388608,mode=1777":
        raise IsolationUnavailable("unsafe writable storage")
    allowed_env = {"PATH", "LANG", "PYTHON_VERSION", "PYTHON_SHA256", "GPG_KEY"}
    if any(value.split("=", 1)[0] not in allowed_env for value in config.get("Env", [])):
        raise IsolationUnavailable("unexpected sandbox environment")


class GVisor:
    def __init__(self, client, settings, *, admission_required=True):
        self.client, self.settings = client, settings
        self.admission_required = admission_required
        self.verified_at = 0.0
        self.quarantined = False

    def watchdog_ready(self):
        try:
            value = json.loads((self.settings.state_dir / "watchdog.json").read_text())
            if not 0 <= time.time() - value["time"] < 3:
                raise ValueError("stale watchdog")
            os.kill(value["pid"], 0)
            if value["started"] != process_birth(value["pid"]):
                raise ValueError("watchdog PID was reused")
        except (OSError, ValueError, KeyError, TypeError):
            raise IsolationUnavailable("independent watchdog unavailable") from None

    def verify(self):
        if self.quarantined:
            raise IsolationUnavailable("controller quarantined after cleanup failure")
        self.watchdog_ready()
        if self.client.containers.list(all=True, filters={"label": LABEL}):
            raise IsolationUnavailable("orphan sandbox pending cleanup")
        info = self.client.info()
        check_daemon(info)
        if self.admission_required:
            from runner.admission import check_admission

            check_admission(self.settings, info)
        image = self.client.images.get(self.settings.image)
        if (
            image.id != self.settings.image
            or image.attrs["Config"].get("Labels", {}).get("org.codejudge.sandbox") != "python-stdio-v1"
            or image.attrs["Config"].get("Entrypoint")
            != ["/usr/local/bin/python", "-I", "-S", "-B", "/opt/bootstrap.py"]
            or image.attrs["Config"].get("User") != "65532:65532"
            or image.attrs["Config"].get("Volumes")
        ):
            raise IsolationUnavailable("unapproved guest image")
        if time.monotonic() - self.verified_at < 30:
            return
        outcome = self._execute({"mode": "probe"})
        try:
            report = json.loads(outcome.stdout)
            valid = outcome.reason is None and report == {
                "uid": 65532,
                "env_safe": True,
                "limits": True,
                "fork_denied": True,
                "network_denied": True,
                "root_readonly": True,
            }
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise IsolationUnavailable("guest isolation probe failed")
        self.verified_at = time.monotonic()

    def execute(self, source, stdin, *, deadline=None):
        self.verify()
        if deadline is not None and time.monotonic() >= deadline:
            raise IsolationUnavailable("request budget exhausted")
        return self._execute({"mode": "run", "source": source, "stdin": stdin}, deadline=deadline)

    def _execute(self, payload, *, deadline=None):
        container = None
        attached = None
        start = time.monotonic()
        budget_shortened = deadline is not None and deadline < start + WALL_SECONDS
        deadline = min(start + WALL_SECONDS, deadline) if deadline is not None else start + WALL_SECONDS
        stdout = bytearray()
        total = 0
        reason = None
        source_released = False
        try:
            container = self.client.containers.create(
                self.settings.image,
                runtime="runsc",
                network_mode="none",
                user="65532:65532",
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                mem_limit=MEMORY,
                memswap_limit=MEMORY,
                nano_cpus=1000000000,
                pids_limit=PIDS,
                tmpfs={"/tmp": "rw,noexec,nosuid,nodev,size=8388608,mode=1777"},
                environment={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
                use_config_proxy=False,
                stdin_open=True,
                tty=False,
                detach=True,
                ipc_mode="none",
                log_config={"Type": "none"},
                labels={LABEL: str(uuid4()), "org.codejudge.deadline": str(time.time() + WALL_SECONDS + 1)},
            )
            container.start()
            container.reload()
            check_container(container, self.settings.image)
            check_cgroup(container.attrs["State"]["Pid"])
            # Until all checks pass the guest bootstrap is waiting for input, not executing source.
            self.watchdog_ready()
            attached = self.client.api.attach_socket(
                container.id, params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1}
            )
            sock = attached._sock
            if time.monotonic() >= deadline:
                raise IsolationUnavailable("sandbox startup exceeded deadline")
            sock.settimeout(max(0.01, deadline - time.monotonic()))
            sock.sendall(json.dumps(payload, ensure_ascii=False).encode() + b"\n")
            source_released = True

            def read_exact(size):
                value = bytearray()
                while len(value) < size:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    sock.settimeout(remaining)
                    part = sock.recv(size - len(value))
                    if not part:
                        if value:
                            raise IsolationUnavailable("truncated sandbox stream")
                        return b""
                    value.extend(part)
                return bytes(value)

            while True:
                header = read_exact(8)
                if not header:
                    break
                size = int.from_bytes(header[4:8], "big")
                if header[0] not in {1, 2} or header[1:4] != b"\x00\x00\x00":
                    raise IsolationUnavailable("invalid sandbox stream")
                total += size
                if total > OUTPUT_BYTES:
                    reason = "output_limit"
                    break
                part = read_exact(size)
                if len(part) != size:
                    raise IsolationUnavailable("truncated sandbox output")
                if header[0] == 1:
                    stdout.extend(part)
            if reason is None:
                status = container.wait(timeout=max(0.01, deadline - time.monotonic()))["StatusCode"]
                container.reload()
                if container.attrs["State"].get("OOMKilled"):
                    reason = "memory_limit"
                elif status != 0:
                    reason = "time_limit" if status == 152 else "runtime_error"
        except (TimeoutError, socket.timeout):
            if not source_released:
                raise IsolationUnavailable("sandbox startup timed out") from None
            if budget_shortened:
                raise IsolationUnavailable("request budget exhausted") from None
            reason = "time_limit"
        except IsolationUnavailable:
            raise
        except Exception:
            if source_released and time.monotonic() >= deadline and not budget_shortened:
                reason = "time_limit"
            else:
                raise IsolationUnavailable("sandbox lifecycle failed") from None
        finally:
            close_failed = False
            if attached:
                try:
                    attached.close()
                except Exception:
                    close_failed = True
            if container:
                try:
                    container.remove(force=True)
                except Exception as exc:
                    if getattr(exc, "status_code", None) == 404:
                        pass
                    else:
                        self.quarantined = True
                        raise IsolationUnavailable("sandbox cleanup failed") from None
                    # Stop accepting work if cleanup cannot be guaranteed.
            if close_failed:
                self.quarantined = True
                raise IsolationUnavailable("sandbox stream cleanup failed") from None

        return Outcome(bytes(stdout), reason, min(10000, int((time.monotonic() - start) * 1000)))
