"""Trusted guest bootstrap. This file is only launched inside a verified gVisor sandbox."""

import json
import os
import resource
import sys

LIMITS = {
    resource.RLIMIT_CPU: (1, 2),
    resource.RLIMIT_AS: (128 * 1024 * 1024, 128 * 1024 * 1024),
    resource.RLIMIT_NPROC: (1, 1),
    resource.RLIMIT_NOFILE: (32, 32),
    resource.RLIMIT_FSIZE: (32768, 32768),
    resource.RLIMIT_CORE: (0, 0),
}


def probe():
    import socket

    report = {
        "uid": os.getuid(),
        "env_safe": not any(name for name in os.environ if name not in {"PATH", "LANG"}),
        "limits": True,
    }
    for kind, expected in LIMITS.items():
        report["limits"] &= resource.getrlimit(kind) == expected
    try:
        pid = os.fork()
    except OSError:
        report["fork_denied"] = True
    else:
        if pid == 0:
            os._exit(0)
        os.waitpid(pid, 0)
        report["fork_denied"] = False
    # External and link-local/internal destinations must be unreachable.
    for address in ["1.1.1.1", "169.254.169.254", "172.17.0.1"]:
        sock = socket.socket()
        sock.settimeout(0.2)
        try:
            sock.connect((address, 80))
            report["network_denied"] = False
            break
        except OSError:
            report.setdefault("network_denied", True)
        finally:
            sock.close()
    report["root_readonly"] = False
    try:
        with open("/escape-check", "w") as stream:
            stream.write("probe")
    except OSError:
        report["root_readonly"] = True
    print(json.dumps(report))


def main():
    payload = json.loads(sys.stdin.buffer.readline(131073))
    os.environ.clear()
    os.environ.update(PATH="/usr/local/bin:/usr/bin:/bin", LANG="C.UTF-8")
    for kind, limit in LIMITS.items():
        resource.setrlimit(kind, limit)
    if payload.get("mode") == "probe":
        probe()
        return
    source = payload["source"]
    # Never mount a source directory from the host. Only an ephemeral tmpfs is writable.
    with open("/tmp/solution.py", "w", encoding="utf-8") as stream:
        stream.write(source)
    read_fd, write_fd = os.pipe()
    os.write(write_fd, payload["stdin"].encode("utf-8"))
    os.close(write_fd)
    os.dup2(read_fd, 0)
    os.close(read_fd)
    os.execve("/usr/local/bin/python", ["python", "-I", "-S", "-B", "/tmp/solution.py"], dict(os.environ))


if __name__ == "__main__":
    main()
