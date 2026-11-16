from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.catalog import suites
from app.config import Settings
from app.models import Evaluation, now
from app.schemas import SandboxResult
from app.worker import claim, finish, run_once


@pytest.fixture
def queued(client, auth, task, submission):
    return client.post(
        "/evaluations",
        headers=auth,
        json={
            "task_id": task["id"],
            "submission_reference": submission["id"],
        },
    ).json()


def settings(**kwargs):
    return Settings(_env_file=None, sandbox_url="https://sandbox.example/evaluate", **kwargs)


def stored(factory):
    with factory() as db:
        return db.scalar(select(Evaluation))


def runner_result(passed=3, total=4, feedback="Passed 3 tests"):
    cases = suites()["sum-two-v1"].cases[:total]
    return {
        "tests_passed": passed,
        "tests_total": total,
        "feedback": feedback,
        "case_results": [
            {
                "id": c.id,
                "label": c.label,
                "status": "passed" if i < passed else "failed",
                "reason": None if i < passed else "wrong_answer",
                "duration_ms": 1,
            }
            for i, c in enumerate(cases)
        ],
    }


def test_worker_success_and_payload(factory, queued):
    def handler(request):
        import json

        assert request.headers["Idempotency-Key"] == queued["id"]
        payload = json.loads(request.content)
        assert payload["evaluation_id"] == queued["id"]
        assert payload["task_id"] == queued["task_id"]
        assert payload["submission_reference"] == queued["submission_reference"]
        assert payload["source"].startswith("a,b=")
        assert payload["suite"]["id"] == "sum-two-v1"
        return httpx.Response(200, json=runner_result())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert run_once(factory, settings(), client)
        assert not run_once(factory, settings(), client)
    row = stored(factory)
    assert row.status == "succeeded" and row.score == Decimal("75.00")
    assert row.feedback == "Passed 3 tests" and row.completed_at


def test_missing_sandbox_fails_closed(factory, queued):
    run_once(factory, Settings(_env_file=None))
    row = stored(factory)
    assert row.status == "failed" and row.error == "sandbox_not_configured"
    assert row.score is None


@pytest.mark.parametrize(
    "result",
    [
        {"tests_passed": 5, "tests_total": 4},
        {"tests_passed": -1, "tests_total": 4},
        {"tests_passed": 0, "tests_total": 0},
        {"tests_passed": True, "tests_total": 4},
        {"tests_passed": 1, "tests_total": 1, "score": 100},
        {"tests_passed": 1},
        {"tests_passed": 1, "tests_total": 2, "feedback": "x" * 10001},
    ],
)
def test_invalid_result(factory, queued, result):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=result))) as client:
        run_once(factory, settings(), client)
    row = stored(factory)
    assert row.status == "failed" and row.error == "invalid_sandbox_result"
    assert row.score is None


@pytest.mark.parametrize("status", [400, 401, 302])
def test_permanent_http_failure(factory, queued, status):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status))) as client:
        run_once(factory, settings(), client)
    assert stored(factory).status == "failed"


@pytest.mark.parametrize("mode", ["timeout", "server", "rate_limit"])
def test_bounded_retries(factory, queued, mode):
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("timeout")
        return httpx.Response(503 if mode == "server" else 429)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        for _ in range(3):
            assert run_once(factory, settings(), client)
            assert not run_once(factory, settings(), client)
            with factory.begin() as db:
                db.scalar(select(Evaluation)).available_at = now() - timedelta(seconds=1)
        assert not run_once(factory, settings(), client)
    row = stored(factory)
    assert row.status == "failed" and row.attempts == 3


def test_expired_lease_and_stale_worker(factory, queued):
    old = claim(factory, settings())
    assert claim(factory, settings()) is None
    with factory.begin() as db:
        row = db.scalar(select(Evaluation))
        row.lease_until = now() - timedelta(seconds=1)
    new = claim(factory, settings())
    assert new.id == old.id and new.claim_token != old.claim_token
    result = SandboxResult.model_validate(runner_result(2, 3))
    assert not finish(factory, old, result=result)
    assert finish(factory, new, result=result)
    assert stored(factory).score == Decimal("66.67")


def test_abandoned_job_limit(factory, queued):
    for _ in range(3):
        assert claim(factory, settings())
        with factory.begin() as db:
            db.scalar(select(Evaluation)).lease_until = now() - timedelta(seconds=1)
    assert claim(factory, settings()) is None
    assert stored(factory).error == "retry_limit_exceeded"


@pytest.mark.parametrize("content", [b"not-json", b"x" * 65537])
def test_malformed_or_oversized_response(factory, queued, content):
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content))
    ) as client:
        run_once(factory, settings(), client)
    assert stored(factory).error == "invalid_sandbox_result"


@pytest.mark.parametrize(
    "url",
    [
        "http://sandbox.test/eval",
        "file:///tmp/code",
        "https://user:pass@host/eval",
        "https://host/eval?token=secret",
    ],
)
def test_insecure_sandbox_configuration(url):
    with pytest.raises(ValueError):
        Settings(_env_file=None, sandbox_url=url)


def test_runner_authentication(factory, queued):
    from pydantic import SecretStr

    def handler(request):
        assert request.headers["Authorization"] == "Bearer runner-credential"
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, json=runner_result(0))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run_once(factory, settings(sandbox_token=SecretStr("runner-credential")), client)
    assert stored(factory).score == Decimal("0.00")


def test_compressed_response_rejected(factory, queued):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Encoding": "identity-unexpected"},
                content=b"{}",
            )
        )
    ) as client:
        run_once(factory, settings(), client)
    assert stored(factory).error == "invalid_sandbox_result"
