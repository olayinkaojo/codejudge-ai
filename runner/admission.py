"""Short-lived signed admission evidence, bound to this host boot, runtime binary, and guest image."""

import hashlib
import hmac
import json
import time
from pathlib import Path

from runner.isolation import IsolationUnavailable


def identity(settings, info):
    runtime = info["Runtimes"]["runsc"]
    path = Path(runtime["path"])
    if not path.is_absolute():
        raise IsolationUnavailable("runsc must use an absolute audited binary path")
    return {
        "image": settings.image,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "runtime_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "runtime_args": runtime.get("runtimeArgs", []),
        "protocol": "python-stdio-v1",
    }


def signature(settings, value):
    return hmac.new(
        settings.token.get_secret_value().encode(),
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()


def check_admission(settings, info):
    try:
        report = json.loads((settings.state_dir / "admission.json").read_text())
        signed = report.pop("signature")
        if not hmac.compare_digest(signed, signature(settings, report)):
            raise ValueError("invalid signature")
        if (
            report["identity"] != identity(settings, info)
            or not 0 <= time.time() - report["validated_at"] < 3600
        ):
            raise ValueError("stale deployment validation")
        if report["checks"] != CHECKS:
            raise ValueError("incomplete validation")
    except (OSError, ValueError, KeyError, TypeError):
        raise IsolationUnavailable("deployment security validation missing, stale, or invalid") from None


CHECKS = [
    "correctness",
    "forged_result",
    "environment",
    "filesystem",
    "network",
    "process",
    "memory",
    "cpu",
    "wall_time",
    "stdout",
    "stderr",
]
