from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from app.models import CodeReview
from tests.conftest import authenticate


def test_resource_replays_and_conflicts(client, auth, task):
    cases = [
        ("/tasks", {"title": "Replay task", "description": "Keep this challenge once"}),
        ("/evaluations", {"task_id": task["id"], "submission_reference": "replay-artifact"}),
        ("/reviews", {"source": "print('one review')", "task_id": task["id"]}),
    ]
    bob = authenticate(client, "bob")
    for path, payload in cases:
        headers = {**auth, "Idempotency-Key": str(uuid4())}
        first = client.post(path, headers=headers, json=payload)
        assert first.status_code in (201, 202)
        assert first.json()["id"] == headers["Idempotency-Key"]
        second = client.post(path, headers=headers, json=payload)
        assert second.json() == first.json()
        changed = {**payload, next(k for k in payload if k != "task_id"): "different-content"}
        assert client.post(path, headers=headers, json=changed).status_code == 409
        foreign = {**bob, "Idempotency-Key": headers["Idempotency-Key"]}
        if path == "/tasks":
            assert client.post(path, headers=foreign, json=payload).status_code == 404
        assert (
            client.post(path, headers={**auth, "Idempotency-Key": "invalid"}, json=payload).status_code == 422
        )


def test_review_replay_does_not_incur_usage_or_rerun_provider(client, auth, monkeypatch):
    from app.review_provider import mock_review

    provider = Mock(return_value=mock_review("pass").model_dump())
    monkeypatch.setattr("app.reviews.review", provider)
    headers = {**auth, "Idempotency-Key": str(uuid4())}
    for _ in range(5):
        assert client.post("/reviews", headers=headers, json={"source": "pass"}).status_code == 201
    assert provider.call_count == 1
    assert len(client.get("/reviews", headers=auth).json()) == 1


def test_postgres_concurrent_review_replay(client, auth, factory, monkeypatch):
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL cross-connection locks")
    from app.review_provider import mock_review

    provider = Mock(return_value=mock_review("pass").model_dump())
    monkeypatch.setattr("app.reviews.review", provider)
    headers = {**auth, "Idempotency-Key": str(uuid4())}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(lambda _: client.post("/reviews", headers=headers, json={"source": "pass"}), range(4))
        )
    assert all(r.status_code == 201 for r in responses)
    assert {r.json()["id"] for r in responses} == {headers["Idempotency-Key"]}
    assert provider.call_count == 1
    with factory() as db:
        assert db.get(CodeReview, UUID(headers["Idempotency-Key"])) is not None


def test_review_replay_rejects_other_owners_and_expired_results(client, auth, factory):
    from datetime import timedelta

    from app.reviews import clock

    headers = {**auth, "Idempotency-Key": str(uuid4())}
    assert client.post("/reviews", headers=headers, json={"source": "pass"}).status_code == 201
    bob = authenticate(client, "bob")
    assert (
        client.post(
            "/reviews",
            headers={**bob, "Idempotency-Key": headers["Idempotency-Key"]},
            json={"source": "pass"},
        ).status_code
        == 404
    )
    with factory() as db:
        record = db.get(CodeReview, UUID(headers["Idempotency-Key"]))
        record.expires_at = clock() - timedelta(seconds=1)
        db.commit()
    assert client.post("/reviews", headers=headers, json={"source": "pass"}).status_code == 409
