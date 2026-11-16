"""Controlled PostgreSQL upgrade for free-tier startup; never resets/stamps/downgrades."""

import logging
import time

from alembic import command
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.database_status import DatabaseStatusError, check_database, migration_config, report_failure
from app.db import database_engine

LOCK_KEY = 732347850135  # Stable, application-specific PostgreSQL session advisory lock.
logger = logging.getLogger(__name__)


def upgrade_database(engine=None, lock_timeout=30):
    owned = engine is None
    engine = engine or database_engine()
    try:
        if engine.dialect.name != "postgresql":
            raise DatabaseStatusError("migration_configuration_error")
        with engine.connect() as connection:
            acquired = False
            try:
                deadline = time.monotonic() + lock_timeout
                while True:
                    acquired = connection.execute(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
                    ).scalar_one()
                    connection.commit()
                    if acquired:
                        break
                    if time.monotonic() >= deadline:
                        raise DatabaseStatusError("migration_lock_timeout")
                    time.sleep(min(0.25, max(0, deadline - time.monotonic())))
                # Bound lock waits and statements during DDL. PostgreSQL's Alembic
                # transaction rolls back failed upgrades; never auto-stamp an existing DB.
                connection.execute(text("SET lock_timeout = '5s'"))
                connection.execute(text("SET statement_timeout = '120s'"))
                connection.commit()
                config = migration_config()
                current = MigrationContext.configure(connection).get_current_heads()
                script = ScriptDirectory.from_config(config)
                try:
                    for revision in current:
                        script.get_revision(revision)
                except Exception:
                    raise DatabaseStatusError("schema_version_mismatch") from None
                connection.commit()
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                check_database(connection)
                logger.info("database_migrations_complete schema=ready")
            finally:
                connection.rollback()
                if acquired:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                    connection.commit()
    finally:
        if owned:
            engine.dispose()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        upgrade_database()
    except Exception as exc:
        report_failure(exc, "migration")
        logger.error("database_migrations_failed; server must not start; inspect safe diagnostic category")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
