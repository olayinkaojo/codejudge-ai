"""Upgrade-only checks against an explicitly disposable local/CI PostgreSQL database."""

import logging
import os
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.config import Settings
from app.database_status import DatabaseStatusError, check_database, migration_config, report_failure
from app.migrate import LOCK_KEY, upgrade_database

pytestmark = pytest.mark.skipif(
    not os.getenv("MIGRATION_TEST_DATABASE_URL"),
    reason="requires dedicated PostgreSQL migration test database",
)


@pytest.fixture
def engine():
    url = Settings(_env_file=None, database_url=os.environ["MIGRATION_TEST_DATABASE_URL"]).database_url
    from sqlalchemy.engine import make_url

    if not (make_url(url).database or "").endswith("_migration_test"):
        pytest.fail("Refusing migration verification outside a dedicated *_migration_test database")
    value = create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 5})
    yield value
    value.dispose()


def test_upgrade_repeatability_and_model_compatibility_preserve_rows(engine, caplog):
    if not inspect(engine).has_table("users"):
        with engine.connect() as connection, pytest.raises(Exception) as missing:
            check_database(connection)
        with caplog.at_level(logging.ERROR):
            report_failure(missing.value, "readiness")
        assert "category=schema_missing" in caplog.text
    upgrade_database(engine)
    fixture_id = uuid4()
    username = "migration_" + fixture_id.hex
    with engine.begin() as db:
        db.execute(
            text("INSERT INTO users (id, username, password_hash) VALUES (:id, :username, :hash)"),
            {"id": fixture_id, "username": username, "hash": "synthetic-test-hash-not-a-credential"},
        )
    # Same command a second time must not recreate tables or delete/overwrite records.
    upgrade_database(engine)
    with engine.connect() as db:
        check_database(db)
        assert (
            db.execute(text("SELECT username FROM users WHERE id=:id"), {"id": fixture_id}).scalar_one()
            == username
        )
        config = migration_config()
        config.attributes["connection"] = db
        command.check(config)


def test_concurrent_migration_lock_fails_safely_and_is_repeatable(engine):
    with engine.connect() as holder:
        holder.execute(text("SELECT pg_advisory_lock(:key)"), {"key": LOCK_KEY})
        holder.commit()
        try:
            with pytest.raises(DatabaseStatusError, match="migration_lock_timeout"):
                upgrade_database(engine, lock_timeout=0.05)
        finally:
            holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
            holder.commit()
    upgrade_database(engine)
    with engine.connect() as connection:
        check_database(connection)


def test_phase4_additive_upgrade_preserves_legacy_records(engine):
    # This fixture refuses every database without the dedicated migration-test suffix.
    with engine.connect() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.downgrade(config, "00391b88d2bb")
    owner, task, evaluation = uuid4(), uuid4(), uuid4()
    with engine.begin() as db:
        db.execute(
            text("INSERT INTO users (id,username,password_hash) VALUES (:id,:name,'synthetic')"),
            {"id": owner, "name": "legacy_" + owner.hex},
        )
        db.execute(
            text(
                "INSERT INTO tasks (id,owner_id,title,description,max_score,created_at) VALUES (:id,:owner,'Legacy','Preserve this challenge',100,now())"
            ),
            {"id": task, "owner": owner},
        )
        db.execute(
            text(
                "INSERT INTO evaluations (id,task_id,owner_id,submission_reference,status,attempts,created_at) VALUES (:id,:task,:owner,'legacy-artifact','queued',0,now())"
            ),
            {"id": evaluation, "task": task, "owner": owner},
        )
    upgrade_database(engine)
    with engine.connect() as db:
        assert (
            db.execute(
                text("SELECT submission_reference FROM evaluations WHERE id=:id"), {"id": evaluation}
            ).scalar_one()
            == "legacy-artifact"
        )
        assert db.execute(text("SELECT title FROM tasks WHERE id=:id"), {"id": task}).scalar_one() == "Legacy"
        assert inspect(db).has_table("code_reviews")
        check_database(db)
