from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.auth import token_digest
from app.models import Token, User, now
from tests.conftest import authenticate


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    assert client.get("/openapi.json").status_code == 200


def test_task_and_evaluation(client, auth, task, submission):
    assert client.get("/tasks/" + task["id"], headers=auth).json() == task
    assert client.get("/tasks", headers=auth).json() == [task]
    result = client.post(
        "/evaluations",
        headers=auth,
        json={
            "task_id": task["id"],
            "submission_reference": submission["id"],
        },
    )
    assert result.status_code == 202
    evaluation = result.json()
    assert evaluation["status"] == "queued"
    assert evaluation["score"] is None
    assert client.get("/evaluations/" + evaluation["id"], headers=auth).json() == evaluation
    assert client.get("/tasks?limit=101", headers=auth).status_code == 422


@pytest.mark.parametrize(
    "extra", [{"tests_passed": 5, "tests_total": 4}, {"score": 100}, {"status": "succeeded"}]
)
def test_invalid_evaluation(client, auth, task, extra):
    result = client.post(
        "/evaluations",
        headers=auth,
        json={
            "task_id": task["id"],
            "submission_reference": "example-1",
            **extra,
        },
    )
    assert result.status_code == 422


def test_missing_task(client, auth):
    assert client.get("/tasks/" + str(uuid4()), headers=auth).status_code == 404
    assert client.get("/tasks/not-found", headers=auth).status_code == 422
    assert (
        client.post(
            "/evaluations",
            headers=auth,
            json={
                "task_id": str(uuid4()),
                "submission_reference": "artifact",
            },
        ).status_code
        == 404
    )


@pytest.mark.parametrize("path", ["/tasks", "/tasks/" + str(uuid4()), "/evaluations/" + str(uuid4())])
def test_auth_required(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_ownership(client, auth, task, submission):
    evaluation = client.post(
        "/evaluations",
        headers=auth,
        json={
            "task_id": task["id"],
            "submission_reference": submission["id"],
        },
    ).json()
    other = authenticate(client, "bob")
    assert client.get("/tasks", headers=other).json() == []
    assert client.get("/tasks/" + task["id"], headers=other).status_code == 404
    assert client.get("/evaluations/" + evaluation["id"], headers=other).status_code == 404
    assert (
        client.post(
            "/evaluations",
            headers=other,
            json={
                "task_id": task["id"],
                "submission_reference": submission["id"],
            },
        ).status_code
        == 404
    )


def test_auth_storage_logout_and_expiry(client, auth, factory):
    raw = auth["Authorization"].split()[1]
    with factory() as db:
        user = db.scalar(select(User))
        assert "correct horse" not in user.password_hash
        token = db.scalar(select(Token))
        assert token.digest == token_digest(raw) and token.digest != raw
    assert client.delete("/auth/token", headers=auth).status_code == 204
    assert client.get("/tasks", headers=auth).status_code == 401
    response = client.post(
        "/auth/token", json={"username": "alice", "password": "correct horse battery staple"}
    )
    raw = response.json()["access_token"]
    with factory() as db:
        db.get(Token, token_digest(raw)).expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert client.get("/tasks", headers={"Authorization": "Bearer " + raw}).status_code == 401


def test_invalid_credentials(client, auth):
    assert (
        client.post(
            "/auth/register",
            json={
                "username": "ALICE",
                "password": "correct horse battery staple",
            },
        ).status_code
        == 409
    )
    for username in ["alice", "unknown"]:
        r = client.post("/auth/token", json={"username": username, "password": "a wrong password"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid credentials"
    response = client.post("/auth/register", json={"username": "user", "password": "secret"})
    assert response.status_code == 422
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "  ", "description": "long description"},
        {"title": "Valid", "description": "short"},
        {"title": "Valid", "description": "long description", "max_score": True},
        {"title": "Valid", "description": "long description", "max_score": 0},
        {"title": "Valid", "description": "x" * 20001},
        {"title": "Valid", "description": "long description", "owner_id": str(uuid4())},
    ],
)
def test_task_validation(client, auth, payload):
    assert client.post("/tasks", headers=auth, json=payload).status_code == 422


@pytest.mark.parametrize("reference", ["https://evil.test/code", "../code", "run me", ";rm", "x" * 257, ""])
def test_artifact_validation(client, auth, task, reference):
    assert (
        client.post(
            "/evaluations",
            headers=auth,
            json={
                "task_id": task["id"],
                "submission_reference": reference,
            },
        ).status_code
        == 422
    )


def test_body_limit(client, auth):
    response = client.post("/tasks", headers=auth, content=b"x" * 131073)
    assert response.status_code == 413
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_database_readiness_failure(client, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    def broken(*args, **kwargs):
        raise OperationalError("hidden SQL", {}, Exception("private details"))

    monkeypatch.setattr(Session, "execute", broken)
    response = client.get("/ready")
    assert response.status_code == 503
    assert "private" not in response.text
