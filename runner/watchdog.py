"""Independent deadline reaper. Run as a separately supervised service on the runner host."""

import fcntl
import json
import os
import time

from runner.client import docker_client
from runner.config import RunnerSettings
from runner.isolation import LABEL, process_birth


def reap(client, timestamp=None):
    for container in client.containers.list(all=True, filters={"label": LABEL}):
        # Missing/malformed deadline is itself grounds for immediate removal.
        try:
            deadline = float(container.labels["org.codejudge.deadline"])
            observed = time.time() if timestamp is None else timestamp
            expired = not 0 < deadline - observed <= 7
        except (ValueError, KeyError, TypeError):
            expired = True
        if expired:
            try:
                container.remove(force=True)
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise


def main():
    settings = RunnerSettings()
    settings.validate_secrets()
    directory = settings.state_dir
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(directory / "watchdog.lock", "a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    client = docker_client(settings)
    while True:
        # Only publish health after successful cleanup. Stale heartbeat closes controller readiness.
        reap(client)
        pending = directory / "watchdog.pending"
        pending.write_text(
            json.dumps({"pid": os.getpid(), "started": process_birth(os.getpid()), "time": time.time()})
        )
        pending.replace(directory / "watchdog.json")
        time.sleep(0.25)


if __name__ == "__main__":
    main()
