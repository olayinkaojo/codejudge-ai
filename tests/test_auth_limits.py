from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text, update
from starlette.requests import Request

from app.auth import hash_password
from app.auth_limits import network_identity
from app.config import Settings, get_settings
from app.models import AuthRateBucket, AuthRateSecret, User


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("AUTH_GLOBAL_PER_MINUTE", "20")
    monkeypatch.setenv("AUTH_TRUSTED_PROXY_CIDRS", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def credentials(name="alice", password="synthetic long password"):
    return {"username": name, "password": password}


def test_registration_does_not_enumerate_or_replace_existing_password(client):
    first = client.post("/auth/register", json=credentials())
    duplicate = client.post("/auth/register", json=credentials(password="other synthetic password"))
    assert first.status_code == duplicate.status_code == 201
    assert first.json() == duplicate.json()
    assert "id" not in first.json()
    assert client.post("/auth/token", json=credentials()).status_code == 200
    assert (
        client.post("/auth/token", json=credentials(password="other synthetic password")).status_code == 401
    )


def test_known_unknown_limits_identical_and_no_secret_logs(client, monkeypatch, caplog, factory):
    monkeypatch.setenv("AUTH_PAIR_LOGINS", "2")
    get_settings.cache_clear()
    assert client.post("/auth/register", json=credentials()).status_code == 201
    for name in ("alice", "unknown"):
        for _ in range(2):
            assert (
                client.post("/auth/token", json=credentials(name, "private wrong password")).status_code
                == 401
            )
        result = client.post("/auth/token", json=credentials(name, "private wrong password"))
        assert result.status_code == 429
        assert 1 <= int(result.headers["retry-after"]) <= 300
    assert "private wrong password" not in caplog.text
    assert "alice" not in caplog.text and "unknown" not in caplog.text
    assert "auth_rate_limited" in caplog.text
    with factory() as db:
        keys = db.scalars(select(AuthRateBucket.key)).all()
        assert all(len(key) == 64 and "alice" not in key for key in keys)
        secret = db.get(AuthRateSecret, 1).secret
        db.execute(update(AuthRateBucket).values(reset_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        db.commit()
    # No permanent account lockout; state survives process/settings cache replacement.
    get_settings.cache_clear()
    assert client.post("/auth/token", json=credentials()).status_code == 200
    with factory() as db:
        assert db.get(AuthRateSecret, 1).secret == secret


def test_admission_blocks_before_scrypt_and_shares_global_budget(client, monkeypatch):
    monkeypatch.setenv("AUTH_GLOBAL_PER_MINUTE", "2")
    get_settings.cache_clear()
    assert client.post("/auth/register", json=credentials()).status_code == 201
    assert client.post("/auth/token", json=credentials()).status_code == 200
    password_check = Mock(side_effect=AssertionError("No hash work after denied admission"))
    monkeypatch.setattr("app.main.verify_password", password_check)
    result = client.post("/auth/token", json=credentials())
    assert result.status_code == 429
    assert client.post("/auth/register", json=credentials("other")).status_code == 429
    password_check.assert_not_called()


def test_shared_peer_has_independent_username_pairs(client, monkeypatch):
    monkeypatch.setenv("AUTH_PAIR_LOGINS", "2")
    get_settings.cache_clear()
    for _ in range(2):
        assert client.post("/auth/token", json=credentials("unknown")).status_code == 401
    assert client.post("/auth/token", json=credentials("unknown")).status_code == 429
    assert client.post("/auth/register", json=credentials("alice")).status_code == 201
    assert client.post("/auth/token", json=credentials("alice")).status_code == 200


def test_missing_rate_table_fails_closed(client, factory, monkeypatch):
    with factory() as db:
        db.execute(text("DROP TABLE auth_rate_buckets"))
        db.commit()
    password_check = Mock()
    monkeypatch.setattr("app.main.verify_password", password_check)
    assert client.post("/auth/token", json=credentials()).status_code == 503
    password_check.assert_not_called()


def request(peer, chain=""):
    return Request({"type": "http", "client": (peer, 123), "headers": [(b"x-forwarded-for", chain.encode())]})


def test_proxy_chain_trust_and_ipv6_grouping():
    default = Settings(_env_file=None)
    assert network_identity(request("198.51.100.2", "1.1.1.1"), default) == "198.51.100.2"
    trusted = Settings(_env_file=None, auth_trusted_proxy_cidrs="10.0.0.0/24")
    assert network_identity(request("10.0.0.1", "1.1.1.1, 198.51.100.2, 10.0.0.2"), trusted) == "198.51.100.2"
    assert network_identity(request("10.0.0.1", "bad-input"), trusted) == "10.0.0.1"
    assert network_identity(request("10.0.0.1", ",".join(["1.1.1.1"] * 9)), trusted) == "10.0.0.1"
    assert network_identity(request("10.0.0.1", "x" * 513), trusted) == "10.0.0.1"
    assert network_identity(request("2001:db8::1"), default) == network_identity(
        request("2001:db8::2"), default
    )
    assert network_identity(request("::ffff:198.51.100.2"), default) == "198.51.100.2"
    assert network_identity(request("unknown", "1.1.1.1"), default) == "unresolved-peer"
    for value in ("0.0.0.0/0", "::/0", "invalid"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, auth_trusted_proxy_cidrs=value)


def test_postgres_concurrent_admission(client, factory, monkeypatch):
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL atomic counters")
    monkeypatch.setenv("AUTH_GLOBAL_PER_MINUTE", "2")
    get_settings.cache_clear()
    with factory() as db:
        db.add(User(username="alice", password_hash=hash_password("synthetic long password")))
        db.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(
            pool.map(lambda _: client.post("/auth/token", json=credentials()).status_code, range(4))
        )
    assert sorted(statuses) == [200, 200, 429, 429]


def test_spoofed_headers_do_not_bypass_admission(client, monkeypatch):
    monkeypatch.setenv("AUTH_PAIR_LOGINS", "2")
    get_settings.cache_clear()
    for suffix in ("1", "2"):
        assert (
            client.post(
                "/auth/token",
                json=credentials("unknown"),
                headers={"X-Forwarded-For": "198.51.100." + suffix},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/auth/token", json=credentials("unknown"), headers={"X-Forwarded-For": "198.51.100.3"}
        ).status_code
        == 429
    )


def test_registration_network_cap_and_stale_cleanup(client, factory, monkeypatch):
    monkeypatch.setenv("AUTH_NETWORK_REGISTRATIONS", "2")
    get_settings.cache_clear()
    with factory() as db:
        db.add(AuthRateBucket(key="f" * 64, hits=1, reset_at=datetime.now(timezone.utc) - timedelta(days=2)))
        db.commit()
    for name in ("alice", "bob"):
        assert client.post("/auth/register", json=credentials(name)).status_code == 201
    assert client.post("/auth/register", json=credentials("other")).status_code == 429
    # Registration exhaustion does not block existing users' login or sessions.
    login = client.post("/auth/token", json=credentials("alice"))
    assert login.status_code == 200
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert client.get("/tasks", headers=headers).status_code == 200
    assert client.delete("/auth/token", headers=headers).status_code == 204
    with factory() as db:
        assert db.get(AuthRateBucket, "f" * 64) is None


def test_global_denials_do_not_allocate_unbounded_identity_rows(client, monkeypatch, factory):
    monkeypatch.setenv("AUTH_GLOBAL_PER_MINUTE", "2")
    get_settings.cache_clear()
    for _ in range(2):
        assert client.post("/auth/token", json=credentials("unknown")).status_code == 401
    with factory() as db:
        before = len(db.scalars(select(AuthRateBucket)).all())
    for i in range(10):
        assert client.post("/auth/token", json=credentials("random_user_" + str(i))).status_code == 429
    with factory() as db:
        assert len(db.scalars(select(AuthRateBucket)).all()) == before
