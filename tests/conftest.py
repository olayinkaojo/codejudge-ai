import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
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
    # Unit-test fixture only: handcrafted schema needs an explicit revision marker.
    # Production uses app.migrate and never stamps/recreates an existing schema.
    from app.database_status import expected_heads

    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
            {"head": next(iter(expected_heads()))},
        )
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
            "description": "Return indices of two values summing to target.",
        },
    )
    assert response.status_code == 201
    return response.json()
