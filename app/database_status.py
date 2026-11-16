"""Read-only schema checks and allowlisted diagnostics. Never log raw DB exceptions."""

import logging
import re
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


class DatabaseStatusError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


def migration_config():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations").replace("%", "%%"))
    return config


def expected_heads():
    heads = set(ScriptDirectory.from_config(migration_config()).get_heads())
    if len(heads) != 1:
        raise DatabaseStatusError("migration_configuration_error")
    return heads


def check_database(db):
    from app import models  # noqa: F401
    from app.db import Base

    db.execute(text("SELECT 1"))
    # LIMIT 0 validates every mapped table/column without reading user rows or writing data.
    for table in Base.metadata.sorted_tables:
        db.execute(select(*table.columns).limit(0))
    connection = db.connection() if isinstance(db, Session) else db
    current = set(MigrationContext.configure(connection).get_current_heads())
    if not current:
        raise DatabaseStatusError("schema_version_missing")
    if current != expected_heads():
        raise DatabaseStatusError("schema_version_mismatch")


def classify_failure(exc):
    if isinstance(exc, DatabaseStatusError):
        return exc.category, None
    if isinstance(exc, (ValidationError, ArgumentError, ValueError)):
        return "configuration_error", None
    if isinstance(exc, ModuleNotFoundError):
        return "driver_unavailable", None
    original = getattr(exc, "orig", exc)
    state = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    state = state if isinstance(state, str) and re.fullmatch(r"[0-9A-Z]{5}", state) else None
    if state in {"28P01", "28000"}:
        return "authentication_failed", state
    if state == "3D000":
        return "database_not_found", state
    if state in {"42P01", "42703"}:
        return "schema_missing", state
    if state == "42P07":
        return "schema_conflict", state
    if state == "42501":
        return "permission_denied", state
    if state in {"57014", "55P03"}:
        return "database_timeout", state
    if state and state.startswith("08"):
        return "connection_unavailable", state
    # Initial libpq connection failures do not always include SQLSTATE. Inspect
    # recognized messages privately; never emit the original text, URL, host or username.
    message = str(original).lower()
    if "password authentication failed" in message:
        return "authentication_failed", state
    if any(
        marker in message
        for marker in ["could not translate host name", "name or service not known", "failed to resolve"]
    ):
        return "dns_failure", state
    if any(
        marker in message
        for marker in [
            "connection refused",
            "timeout expired",
            "connection timed out",
            "server closed the connection",
        ]
    ):
        return "connection_unavailable", state
    return "database_error", state


def report_failure(exc, operation):
    category, state = classify_failure(exc)
    # No exc_info, exception repr, SQL parameters, connection string or arbitrary message.
    logger.error(
        "database_operation_failed operation=%s category=%s sqlstate=%s",
        operation,
        category,
        state or "unknown",
    )
