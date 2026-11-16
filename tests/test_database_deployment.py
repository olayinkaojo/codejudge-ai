import logging
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.config import Settings
from app.database_status import report_failure


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_render_urls_use_psycopg3_without_losing_credentials_or_tls_options(scheme):
    value = f"{scheme}://test_user:p%40ss%3Aword%25@db.example/app?sslmode=verify-full&connect_timeout=4"
    config = Settings(_env_file=None, database_url=value)
    url = make_url(config.database_url)
    assert url.drivername == "postgresql+psycopg"
    assert url.username == "test_user" and url.password == "p@ss:word%"
    assert url.host == "db.example" and url.database == "app"
    assert url.query == {"sslmode": "verify-full", "connect_timeout": "4"}
    assert "p%40ss" not in repr(config) and "p@ss" not in repr(config)


@pytest.mark.parametrize(
    "value",
    [
        "not-a-url-PRIVATE_VALUE",
        "mysql://user:PRIVATE_VALUE@host/db",
        "postgresql+psycopg2://user:PRIVATE_VALUE@host/db",
    ],
)
def test_bad_configuration_never_echoes_url(value):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url=value)
    assert "PRIVATE_VALUE" not in str(error.value)


@pytest.mark.parametrize(
    "state,category",
    [
        ("28P01", "authentication_failed"),
        ("28000", "authentication_failed"),
        ("3D000", "database_not_found"),
        ("42P01", "schema_missing"),
        ("42703", "schema_missing"),
        ("42501", "permission_denied"),
        ("08006", "connection_unavailable"),
        ("57014", "database_timeout"),
        ("42P07", "schema_conflict"),
    ],
)
def test_structured_diagnostics_are_allowlisted_and_redacted(state, category, caplog):
    original = Exception("SECRET_PASSWORD full connection-string private host SQL parameters")
    original.sqlstate = state
    exc = OperationalError("SENSITIVE_SQL", {"password": "SECRET_PASSWORD"}, original)
    with caplog.at_level(logging.ERROR):
        report_failure(exc, "readiness")
    assert f"category={category}" in caplog.text
    assert f"sqlstate={state}" in caplog.text
    assert "SECRET_PASSWORD" not in caplog.text and "SENSITIVE_SQL" not in caplog.text


@pytest.mark.parametrize(
    "message,category",
    [
        ("password authentication failed for user PRIVATE_USER", "authentication_failed"),
        ("could not translate host name PRIVATE_HOST", "dns_failure"),
        ("connection refused SECRET_PASSWORD", "connection_unavailable"),
        ("unknown PRIVATE_CONNECTION_STRING", "database_error"),
    ],
)
def test_initial_libpq_failure_classification_does_not_log_original(message, category, caplog):
    with caplog.at_level(logging.ERROR):
        report_failure(OperationalError("", {}, Exception(message)), "readiness")
    assert (
        f"category={category}" in caplog.text
        and "PRIVATE" not in caplog.text
        and "SECRET_PASSWORD" not in caplog.text
    )


def test_missing_version_and_future_version_are_unready_without_database_changes(client, factory, caplog):
    with factory.begin() as db:
        db.execute(text("DELETE FROM alembic_version"))
    with caplog.at_level(logging.ERROR):
        response = client.get("/ready")
    assert response.status_code == 503 and response.json() == {"detail": "Database unavailable"}
    assert "category=schema_version_missing" in caplog.text
    with factory.begin() as db:
        assert db.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar_one() == 0
        db.execute(text("INSERT INTO alembic_version VALUES ('future_revision')"))
    with caplog.at_level(logging.ERROR):
        assert client.get("/ready").status_code == 503
    assert "category=schema_version_mismatch" in caplog.text
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_required_column_is_safe_and_actionable(client, monkeypatch, caplog):
    from sqlalchemy.orm import Session

    original = Exception("column PRIVATE_COLUMN does not exist; password=PRIVATE_PASSWORD")
    original.sqlstate = "42703"
    monkeypatch.setattr(
        Session, "execute", MagicMock(side_effect=ProgrammingError("private query", {}, original))
    )
    with caplog.at_level(logging.ERROR):
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "category=schema_missing" in caplog.text and "PRIVATE" not in caplog.text


def test_engine_initialization_failure_is_also_safe(monkeypatch, caplog):
    from app.db import get_db

    def unavailable():
        raise ModuleNotFoundError("PRIVATE_DRIVER_CONFIGURATION")

    monkeypatch.setattr("app.db.session_factory", unavailable)
    with caplog.at_level(logging.ERROR), pytest.raises(Exception) as exc:
        next(get_db())
    assert exc.value.status_code == 503
    assert "category=driver_unavailable" in caplog.text and "PRIVATE" not in caplog.text


def test_startup_stops_before_uvicorn_on_migration_failure(monkeypatch):
    from app.start import main

    monkeypatch.setenv("MIGRATE_ON_START", "true")
    monkeypatch.setattr("app.start.migrate", lambda: 1)
    execute = MagicMock()
    monkeypatch.setattr("app.start.os.execvp", execute)
    assert main() == 1
    execute.assert_not_called()


@pytest.mark.parametrize("enabled", ["true", "false"])
def test_startup_opt_in_and_render_port(monkeypatch, enabled):
    from app.start import main

    monkeypatch.setenv("MIGRATE_ON_START", enabled)
    monkeypatch.setenv("PORT", "10000")
    migrate, execute = MagicMock(return_value=0), MagicMock()
    monkeypatch.setattr("app.start.migrate", migrate)
    monkeypatch.setattr("app.start.os.execvp", execute)
    assert main() == 0
    assert migrate.call_count == (1 if enabled == "true" else 0)
    args = execute.call_args.args[1]
    assert args[args.index("--port") + 1] == "10000"
    assert "app.main:app" in args


@pytest.mark.parametrize(
    "setting,value", [("PORT", "invalid"), ("PORT", "65536"), ("MIGRATE_ON_START", "yes-guess")]
)
def test_invalid_startup_settings_fail_closed(monkeypatch, setting, value):
    from app.start import main

    monkeypatch.setenv(setting, value)
    execute = MagicMock()
    monkeypatch.setattr("app.start.os.execvp", execute)
    assert main() == 1
    execute.assert_not_called()


def test_migration_failure_logs_safe_category(monkeypatch, caplog):
    from app.migrate import main

    original = Exception("password authentication failed SECRET_VALUE")
    monkeypatch.setattr(
        "app.migrate.upgrade_database", MagicMock(side_effect=OperationalError("private SQL", {}, original))
    )
    with caplog.at_level(logging.ERROR):
        assert main() == 1
    assert "category=authentication_failed" in caplog.text
    assert "SECRET_VALUE" not in caplog.text and "private SQL" not in caplog.text


def test_readiness_never_writes_or_migrates(client, factory):
    from sqlalchemy import event

    engine = factory.kw["bind"]
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert client.get("/ready").status_code == 200
        assert client.get("/ready").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert statements and set(statements) <= {"SELECT", "PRAGMA"}
