"""Only synthetic loopback databases. No application .env or production access."""

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.auth import hash_password, token_digest, verify_password
from app.database_status import check_database, expected_heads
from app.migrate import upgrade_database
from app.models import CodeReview, Evaluation, Task, Token, User
from app.review_provider import mock_review
from scripts import db_backup


def test_repository_and_credentials_safety(tmp_path, monkeypatch):
    with pytest.raises(db_backup.BackupError):
        db_backup.outside_repo(Path(__file__).parent / "backup.pgdump.gpg")
    credential = tmp_path / "pgpass"
    credential.write_text("synthetic-test-only")
    credential.chmod(0o644)
    with pytest.raises(db_backup.BackupError):
        db_backup.private_file(credential)
    monkeypatch.setenv("DATABASE_URL", "must-not-inherit")
    monkeypatch.setenv("PGPASSWORD", "must-not-inherit")
    assert "DATABASE_URL" not in db_backup.tool_environment()
    assert "PGPASSWORD" not in db_backup.tool_environment()
    monkeypatch.delenv("PGPASSFILE", raising=False)
    with pytest.raises(db_backup.BackupError):
        db_backup.environment()


def test_restore_refuses_live_names_before_decryption(tmp_path, monkeypatch):
    monkeypatch.setattr(db_backup, "environment", lambda: {"PGDATABASE": "production", "PGHOST": "localhost"})
    with pytest.raises(db_backup.BackupError, match="dedicated"):
        db_backup.restore("unused", "unused", tmp_path, "production")
    monkeypatch.setattr(
        db_backup, "environment", lambda: {"PGDATABASE": "safe_restore_test", "PGHOST": "production.example"}
    )
    with pytest.raises(db_backup.BackupError, match="loopback"):
        db_backup.restore("unused", "unused", tmp_path, "safe_restore_test")


@pytest.fixture
def drill(tmp_path):
    raw = os.getenv("BACKUP_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("requires explicitly configured synthetic loopback backup database")
    url = make_url(raw)
    if url.host not in {"localhost", "127.0.0.1"} or not (url.database or "").endswith("_test"):
        pytest.fail("Backup drill refuses non-loopback or non-test connection")
    if any(not shutil.which(tool) for tool in ("gpg", "pg_dump", "pg_restore", "psql")):
        pytest.fail("Backup drill requires PostgreSQL client tools and GnuPG")
    home = tmp_path / "keys"
    home.mkdir(mode=0o700)
    subprocess.run(
        [
            "gpg",
            "--homedir",
            str(home),
            "--batch",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
            "--quick-generate-key",
            "CodeJudge synthetic CI only",
            "rsa2048",
            "encr",
            "1d",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    keys = subprocess.check_output(
        ["gpg", "--homedir", str(home), "--with-colons", "--list-keys"], stderr=subprocess.DEVNULL
    ).decode()
    fingerprint = next(line.split(":")[9] for line in keys.splitlines() if line.startswith("fpr:"))
    pgpass = tmp_path / "pgpass"
    pgpass.write_text(f"{url.host}:*:*:{url.username}:{url.password}\n")
    pgpass.chmod(0o600)
    source = "cj_" + uuid4().hex + "_backup_test"
    target = "cj_" + uuid4().hex + "_restore_test"
    admin = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    created = []
    try:
        with admin.connect() as conn:
            for name in (source, target):
                conn.execute(text(f'CREATE DATABASE "{name}"'))
                created.append(name)
        source_engine = create_engine(url.set(database=source), hide_parameters=True)
        target_engine = create_engine(url.set(database=target), hide_parameters=True)
        upgrade_database(source_engine)
        user_id, task_id = uuid4(), uuid4()
        with Session(source_engine) as db:
            db.add(
                User(
                    id=user_id,
                    username="synthetic_backup_user",
                    password_hash=hash_password("synthetic drill passphrase"),
                )
            )
            db.commit()
            db.add(
                Task(
                    id=task_id,
                    owner_id=user_id,
                    title="Synthetic restore challenge",
                    description="No production records used in this drill.",
                )
            )
            db.commit()
            db.add(
                Token(
                    digest=token_digest("synthetic-restored-token"),
                    user_id=user_id,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                )
            )
            db.add(
                Evaluation(
                    owner_id=user_id, task_id=task_id, submission_reference="synthetic-backup-artifact"
                )
            )
            db.add(
                CodeReview(
                    owner_id=user_id,
                    task_id=task_id,
                    source_digest="0" * 64,
                    line_count=1,
                    provider="mock",
                    status="completed",
                    result=mock_review("pass").model_dump(),
                    deadline=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                )
            )
            db.commit()
        env = {
            **os.environ,
            "PGHOST": url.host,
            "PGPORT": str(url.port or 5432),
            "PGUSER": url.username or "",
            "PGDATABASE": source,
            "PGPASSFILE": str(pgpass),
            "PGSSLMODE": "disable",
        }
        yield tmp_path, home, fingerprint, env, source_engine, target_engine, user_id, task_id
    finally:
        if "source_engine" in locals():
            source_engine.dispose()
            target_engine.dispose()
        with admin.connect() as conn:
            for name in created:
                conn.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()
        subprocess.run(
            ["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def invoke(action, path, home, work, env, extra=()):
    return subprocess.run(
        [
            sys.executable,
            str(db_backup.ROOT / "scripts/db_backup.py"),
            action,
            "--file",
            str(path),
            "--gnupg-home",
            str(home),
            "--work-dir",
            str(work),
            *extra,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


def test_encrypted_backup_verify_restore_and_failures(drill):
    work, home, fingerprint, env, source, target, user_id, task_id = drill
    artifact = work / "synthetic.pgdump.gpg"
    made = invoke("backup", artifact, home, work, env, ("--recipient", fingerprint))
    assert made.returncode == 0, made.stderr
    assert artifact.stat().st_mode & 0o077 == 0
    assert b"synthetic_backup_user" not in artifact.read_bytes()
    assert not list(work.glob("codejudge-backup-*"))
    # Verification is offline, with no libpq target in its environment.
    offline = {k: v for k, v in env.items() if not k.startswith("PG")}
    assert invoke("verify", artifact, home, work, offline).returncode == 0
    restore_env = {**env, "PGDATABASE": target.url.database}
    # An object-only DB is not empty even without tables/rows.
    with target.begin() as connection:
        connection.execute(text("CREATE TYPE synthetic_guard_enum AS ENUM ('synthetic')"))
    assert (
        invoke("restore", artifact, home, work, restore_env, ("--confirm", target.url.database)).returncode
        == 1
    )
    with target.begin() as connection:
        connection.execute(text("DROP TYPE synthetic_guard_enum"))
    restored = invoke("restore", artifact, home, work, restore_env, ("--confirm", target.url.database))
    assert restored.returncode == 0, restored.stderr
    with Session(target) as db:
        user = db.get(User, user_id)
        assert user.username == "synthetic_backup_user"
        assert verify_password("synthetic drill passphrase", user.password_hash)
        assert db.get(Task, task_id).title == "Synthetic restore challenge"
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == next(iter(expected_heads()))
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    def restored_session():
        with Session(target) as db:
            yield db

    app.dependency_overrides[get_db] = restored_session
    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer synthetic-restored-token"}
            assert client.get("/ready").status_code == 200
            assert client.get("/tasks", headers=headers).json()[0]["id"] == str(task_id)
            assert client.get("/reviews", headers=headers).json()[0]["provider"] == "mock"
        with target.connect() as connection:
            check_database(connection)
        with Session(target) as db:
            assert db.scalar(select(Evaluation)).submission_reference == "synthetic-backup-artifact"
            assert db.scalar(select(CodeReview)).result == mock_review("pass").model_dump()
    finally:
        app.dependency_overrides.clear()
    # Existing data is not overwritten; source remains unchanged.
    assert (
        invoke("restore", artifact, home, work, restore_env, ("--confirm", target.url.database)).returncode
        == 1
    )
    with Session(source) as db:
        assert db.scalar(select(User.id)) == user_id
    assert invoke("backup", artifact, home, work, env, ("--recipient", fingerprint)).returncode == 1
    wrong = work / "wrong-key-home"
    wrong.mkdir(mode=0o700)
    assert invoke("verify", artifact, wrong, work, offline).returncode == 1
    damaged = work / "tampered.pgdump.gpg"
    content = bytearray(artifact.read_bytes())
    content[-20] ^= 1
    damaged.write_bytes(content)
    damaged.chmod(0o600)
    assert invoke("verify", damaged, home, work, offline).returncode == 1
    assert (
        invoke("restore", damaged, home, work, restore_env, ("--confirm", target.url.database)).returncode
        == 1
    )
    invalid = work / "valid-encryption-invalid-archive.pgdump.gpg"
    with invalid.open("wb") as output:
        subprocess.run(
            [
                "gpg",
                "--no-options",
                "--homedir",
                str(home),
                "--batch",
                "--trust-model",
                "always",
                "--encrypt",
                "--recipient",
                fingerprint,
            ],
            input=b"Not a PostgreSQL archive",
            stdout=output,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    invalid.chmod(0o600)
    assert invoke("verify", invalid, home, work, offline).returncode == 1
    failed = work / "must-not-exist.pgdump.gpg"
    assert invoke("backup", failed, home, work, env, ("--recipient", "0" * 40)).returncode == 1
    assert not failed.exists()
    missing_db = {**env, "PGDATABASE": "cj_nonexistent_backup_test"}
    assert invoke("backup", failed, home, work, missing_db, ("--recipient", fingerprint)).returncode == 1
    assert not failed.exists()
    assert not list(work.glob("codejudge-restore-*"))


def test_libpq_security_environment(tmp_path, monkeypatch):
    credential = tmp_path / "pgpass"
    credential.write_text("synthetic-only")
    credential.chmod(0o600)
    for key, value in {
        "PGHOST": "db.example.invalid",
        "PGPORT": "5432",
        "PGDATABASE": "example",
        "PGUSER": "example",
        "PGPASSFILE": str(credential),
        "PGSSLMODE": "disable",
        "PGPASSWORD": "do-not-inherit",
        "PGOPTIONS": "do-not-inherit",
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(db_backup.BackupError, match="loopback"):
        db_backup.environment()
    monkeypatch.setenv("PGSSLMODE", "verify-full")
    env = db_backup.environment()
    assert "PGPASSWORD" not in env and "PGOPTIONS" not in env
    monkeypatch.setenv("PGDATABASE", "postgresql://not-a-database-name")
    with pytest.raises(db_backup.BackupError, match="plain"):
        db_backup.environment()
