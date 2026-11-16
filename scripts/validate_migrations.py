"""Destructive migration regression check for a dedicated *_migration_test database only."""

import subprocess
import sys
from uuid import uuid4

from sqlalchemy import create_engine, text

from app.config import get_settings


def migrate(*args):
    subprocess.run([sys.executable, "-m", "alembic", *args], check=True)


def main():
    engine = create_engine(get_settings().database_url, hide_parameters=True)
    if not (engine.url.database or "").endswith("_migration_test"):
        raise SystemExit("Refusing destructive validation outside a dedicated *_migration_test database")
    migrate("upgrade", "head")
    migrate("downgrade", "base")
    migrate("upgrade", "00391b88d2bb")
    user, task, evaluation = uuid4(), uuid4(), uuid4()
    with engine.begin() as db:
        db.execute(
            text("INSERT INTO users (id,username,password_hash) VALUES (:id,:name,:hash)"),
            {"id": user, "name": "migration_fixture", "hash": "not-a-login-credential"},
        )
        db.execute(
            text(
                "INSERT INTO tasks (id,owner_id,title,description,max_score,created_at) VALUES (:id,:owner,:title,:description,100,now())"
            ),
            {
                "id": task,
                "owner": user,
                "title": "Legacy task",
                "description": "Existing legacy task before Phase 3",
            },
        )
        db.execute(
            text(
                "INSERT INTO evaluations (id,task_id,owner_id,submission_reference,status,attempts,created_at) VALUES (:id,:task,:owner,'legacy','queued',0,now())"
            ),
            {"id": evaluation, "task": task, "owner": user},
        )
    migrate("upgrade", "head")
    with engine.connect() as db:
        row = db.execute(
            text("SELECT available_at,case_results FROM evaluations WHERE id=:id"), {"id": evaluation}
        ).one()
        assert row.available_at is not None and row.case_results is None
        assert (
            db.execute(text("SELECT test_suite_id FROM tasks WHERE id=:id"), {"id": task}).scalar_one()
            is None
        )
    migrate("check")
    migrate("downgrade", "00391b88d2bb")
    migrate("upgrade", "head")
    migrate("check")
    migrate("downgrade", "base")
    migrate("upgrade", "head")
    engine.dispose()
    print(
        "Migration checks passed: legacy rows preserved, queue timestamps backfilled, downgrade/re-upgrade and schema drift."
    )


if __name__ == "__main__":
    main()
