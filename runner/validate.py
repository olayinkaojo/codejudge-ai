"""Run trusted adversarial probes in verified gVisor only; issue one hour of admission evidence."""

import json
import time

from contracts.evaluation import RunRequest, Suite
from runner.admission import CHECKS, identity, signature
from runner.client import docker_client
from runner.config import RunnerSettings
from runner.isolation import GVisor, IsolationUnavailable
from runner.service import evaluate


def validate(settings, engine):
    admission = settings.state_dir / "admission.json"
    admission.unlink(missing_ok=True)
    before = identity(settings, engine.client.info())
    # All execute() calls still require runsc, actual cgroups, a safe image, and a live independent watchdog.
    suite = Suite(
        id="admission-v1",
        title="Admission",
        description="Trusted deployment admission probe",
        cases=[{"id": "sum", "label": "Sum", "stdin": "2 3\n", "expected": "5\n"}],
    )

    def request(source):
        from uuid import uuid4

        return RunRequest(
            evaluation_id=uuid4(), task_id=uuid4(), submission_reference=uuid4(), source=source, suite=suite
        )

    result = evaluate(request("a,b=map(int,input().split()); print(a+b)"), engine)
    if result.tests_passed != 1:
        raise IsolationUnavailable("correctness probe failed")
    result = evaluate(request('print(\'{"tests_passed": 1, "tests_total": 1}\')'), engine)
    if result.tests_passed != 0:
        raise IsolationUnavailable("forged verdict probe failed")
    probes = {
        "environment": "import os\nassert set(os.environ) <= {'PATH','LANG'}\nprint('restricted')",
        "filesystem": "import os\nassert not any(os.path.exists(p) for p in ['/var/run/docker.sock','/workspace/.env','/var/lib/codejudge-runner','/proc/1/root/var/lib/codejudge-runner'])\ntry:\n open('/host-write','w')\nexcept OSError:\n print('restricted')",
        "network": "import socket\nfor ip in ['1.1.1.1','169.254.169.254','172.17.0.1','127.0.0.1']:\n s=socket.socket(); s.settimeout(0.2)\n try:\n  s.connect((ip,80))\n  raise RuntimeError('network access')\n except OSError: pass\n finally: s.close()\nprint('restricted')",
        "process": "import os\ntry:\n p=os.fork()\nexcept OSError:\n print('restricted')\nelse:\n os._exit(1)",
        "memory": "try:\n a=bytearray(256*1024*1024)\nexcept MemoryError:\n print('restricted')",
    }
    for name, source in probes.items():
        outcome = engine.execute(source, "")
        if outcome.reason or outcome.stdout != b"restricted\n":
            raise IsolationUnavailable(f"{name} probe failed")
    for name, source, reason in [
        ("cpu", "while True: pass", "time_limit"),
        ("wall_time", "import time; time.sleep(30)", "time_limit"),
        ("stdout", 'print("x"*1000000)', "output_limit"),
        ("stderr", 'import sys; sys.stderr.write("x"*1000000)', "output_limit"),
    ]:
        outcome = engine.execute(source, "")
        if outcome.reason != reason or (name == "cpu" and outcome.duration_ms >= 4500):
            raise IsolationUnavailable(f"{name} enforcement probe failed")
    if before != identity(settings, engine.client.info()):
        raise IsolationUnavailable("runtime changed during validation")
    report = {"identity": before, "validated_at": time.time(), "checks": CHECKS}
    report["signature"] = signature(settings, report)
    pending = settings.state_dir / "admission.pending"
    pending.write_text(json.dumps(report))
    pending.chmod(0o600)
    pending.replace(admission)
    return report


def main():
    settings = RunnerSettings()
    settings.validate_secrets()
    client = docker_client(settings)
    engine = GVisor(client, settings, admission_required=False)
    try:
        engine.verify()
        validate(settings, engine)
    except Exception:
        (settings.state_dir / "admission.json").unlink(missing_ok=True)
        raise SystemExit("Deployment validation FAILED. Runner must remain closed.") from None
    print("Deployment security probes passed. Admission valid for one hour on this host/image/runtime only.")


if __name__ == "__main__":
    main()
