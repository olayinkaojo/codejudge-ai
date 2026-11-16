import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


@pytest.fixture
def factory():
    url = os.getenv("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    if not url.startswith("sqlite") and not (make_url(url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL database name must end with _test; fixtures destroy tables")
    options = (
        {}
        if not url.startswith("sqlite")
        else {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
    )
    engine = create_engine(url, **options)
    # TEST_DATABASE_URL must refer to a dedicated disposable test database.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(factory):
    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def authenticate(client, username="alice"):
    credentials = {"username": username, "password": "correct horse battery staple"}
    assert client.post("/auth/register", json=credentials).status_code == 201
    response = client.post("/auth/token", json=credentials)
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def auth(client):
    return authenticate(client)


@pytest.fixture
def task(client, auth):
    response = client.post(
        "/tasks",
        headers=auth,
        json={
            "title": "Two Sum",
            "test_suite_id": "sum-two-v1",
            "description": "Return indices of two values summing to target.",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def submission(client, auth, task):
    response = client.post(
        "/submissions",
        headers=auth,
        json={"task_id": task["id"], "source": "a,b=map(int,input().split()); print(a+b)"},
    )
    assert response.status_code == 201
    return response.json()
