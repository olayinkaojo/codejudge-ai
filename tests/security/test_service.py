from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.catalog import suites
from contracts.evaluation import RunRequest
from runner.config import RunnerSettings
from runner.isolation import IsolationUnavailable, Outcome
from runner.service import create_app

TOKEN = "synthetic-test-token-more-than-32-characters"
IMAGE = "sha256:" + "a" * 64


class StubEngine:
    """Protocol test double: never executes any Python, shell, or subprocess."""

    available = True
    calls = 0
    source = ""
    forged = False

    def verify(self):
        if not self.available:
            raise IsolationUnavailable("test deployment failure")

    def execute(self, source, stdin, *, deadline=None):
        self.calls += 1
        self.source = source
        outputs = {
            "2 3\n": b"5\n",
            "-7 2\n": b"-5\n",
            " 0\n0 \n": b"0\n",
            "1000000000000000000000000000000 1\n": b"1000000000000000000000000000001\n",
        }
        return Outcome(b'{"tests_passed":4}' if self.forged else outputs[stdin], None, 1)


@pytest.fixture
def runner(tmp_path):
    engine = StubEngine()
    settings = RunnerSettings(token=TOKEN, image=IMAGE, state_dir=tmp_path)
    with TestClient(create_app(settings, engine)) as client:
        yield client, engine, settings


def payload():
    return RunRequest(
        evaluation_id=uuid4(),
        task_id=uuid4(),
        submission_reference=uuid4(),
        source="this source is never executed in protocol tests",
        suite=suites()["sum-two-v1"],
    ).model_dump(mode="json")


def headers(data):
    return {"Authorization": "Bearer " + TOKEN, "Idempotency-Key": data["evaluation_id"]}


def test_authenticated_idempotent_runner_contract(runner):
    client, engine, _ = runner
    data = payload()
    response = client.post("/evaluate", headers=headers(data), json=data)
    assert response.status_code == 200
    assert response.json()["tests_passed"] == 4
    assert len(response.json()["case_results"]) == 4
    assert "expected" not in response.json()["case_results"][0]
    assert client.post("/evaluate", headers=headers(data), json=data).json() == response.json()
    assert engine.calls == 4  # Replay uses durable journal, not repeated execution.
    data["source"] = "different source"
    assert client.post("/evaluate", headers=headers(data), json=data).status_code == 409


def test_forged_guest_json_cannot_award_points(runner):
    client, engine, _ = runner
    engine.forged = True
    data = payload()
    result = client.post("/evaluate", headers=headers(data), json=data).json()
    assert result["tests_passed"] == 0
    assert all(case["reason"] == "wrong_answer" for case in result["case_results"])


def test_unavailable_isolation_returns_no_results_even_for_cached_jobs(runner):
    client, engine, _ = runner
    data = payload()
    assert client.post("/evaluate", headers=headers(data), json=data).status_code == 200
    engine.available = False
    assert client.post("/evaluate", headers=headers(data), json=data).status_code == 503
    assert client.get("/ready", headers=headers(data)).status_code == 503


def test_no_auth_no_execution(runner):
    client, engine, _ = runner
    assert client.post("/evaluate", json=payload()).status_code == 401
    assert engine.calls == 0
    assert client.get("/ready").status_code == 401


def test_wrong_key_invalid_payload_and_body_limits(runner):
    client, engine, _ = runner
    data = payload()
    assert (
        client.post(
            "/evaluate", headers={**headers(data), "Idempotency-Key": str(uuid4())}, json=data
        ).status_code
        == 409
    )
    bad = {**data, "source": "SECRET_SOURCE", "command": "never allowed"}
    response = client.post("/evaluate", headers=headers(data), json=bad)
    assert response.status_code == 422 and "SECRET_SOURCE" not in response.text
    assert client.post("/evaluate", content=b"x" * 131073).status_code == 413
    assert engine.calls == 0


def test_cache_survives_service_restart(runner):
    client, engine, settings = runner
    data = payload()
    expected = client.post("/evaluate", headers=headers(data), json=data).json()
    # A second process is intentionally prohibited; test durable journal directly.
    import hashlib

    from runner.service import Journal

    digest = hashlib.sha256(RunRequest.model_validate(data).model_dump_json().encode()).hexdigest()
    assert Journal(settings.state_dir).lookup(data["evaluation_id"], digest).model_dump() == expected


def test_worker_to_runner_to_durable_report(client, auth, task, submission, factory, runner):
    import httpx

    from app.config import Settings
    from app.worker import run_once

    transport, _, _ = runner
    job = client.post(
        "/evaluations", headers=auth, json={"task_id": task["id"], "submission_reference": submission["id"]}
    ).json()

    def dispatch(request):
        response = transport.post("/evaluate", headers=dict(request.headers), content=request.content)
        return httpx.Response(response.status_code, json=response.json())

    settings = Settings(_env_file=None, sandbox_url="https://runner.test/evaluate", sandbox_token=TOKEN)
    with httpx.Client(transport=httpx.MockTransport(dispatch)) as connection:
        assert run_once(factory, settings, connection)
    report = client.get("/evaluations/" + job["id"], headers=auth).json()
    assert report["status"] == "succeeded" and report["score"] == 100
    assert len(report["case_results"]) == 4
    # The engine here is a protocol double, not evidence that this host can safely run submissions.
