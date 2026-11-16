import json
import time

import pytest

from runner.admission import CHECKS, check_admission, signature
from runner.config import RunnerSettings
from runner.isolation import IsolationUnavailable


@pytest.fixture
def admission(tmp_path, monkeypatch):
    settings = RunnerSettings(
        token="synthetic-test-secret-with-over-32-characters", image="sha256:" + "a" * 64, state_dir=tmp_path
    )
    identity = {"image": settings.image, "boot_id": "test-boot", "runtime_sha256": "test-runtime"}
    monkeypatch.setattr("runner.admission.identity", lambda *_: identity)
    report = {"identity": dict(identity), "validated_at": time.time(), "checks": list(CHECKS)}

    def save():
        signed = {**report, "signature": signature(settings, report)}
        (tmp_path / "admission.json").write_text(json.dumps(signed))

    return settings, report, save


def test_signed_evidence_admits_only_a_fully_checked_deployment(admission):
    settings, _, save = admission
    save()
    check_admission(settings, {})


@pytest.mark.parametrize("invalid", ["missing", "expired", "future", "identity", "incomplete", "signature"])
def test_unverified_deployment_never_admitted(admission, invalid):
    settings, report, save = admission
    if invalid == "expired":
        report["validated_at"] = time.time() - 3601
    if invalid == "future":
        report["validated_at"] = time.time() + 10
    if invalid == "identity":
        report["identity"]["image"] = "different"
    if invalid == "incomplete":
        report["checks"] = ["correctness"]
    if invalid != "missing":
        save()
    if invalid == "signature":
        path = settings.state_dir / "admission.json"
        data = json.loads(path.read_text())
        data["signature"] = "invalid"
        path.write_text(json.dumps(data))
    with pytest.raises(IsolationUnavailable):
        check_admission(settings, {})
