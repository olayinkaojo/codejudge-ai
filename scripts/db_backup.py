"""Operator-only PostgreSQL/GnuPG backup tooling. Never loads application .env files."""

import argparse
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BackupError(Exception):
    pass


def outside_repo(path):
    path = Path(path).resolve()
    if path == ROOT or ROOT in path.parents:
        raise BackupError("Backup/key/work paths must be outside the repository")
    return path


def private_file(path):
    path = outside_repo(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise BackupError("Credential files must be owner-only regular files (0600)")
    return path


def tool_environment():
    # Do not pass application tokens, DATABASE_URL or unrelated secrets to child tools.
    return {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL") if key in os.environ}


def environment():
    # Require explicit libpq fields, no URI/password on argv, no implicit service database.
    required = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSFILE")
    if not all(os.environ.get(key) for key in required):
        raise BackupError("Explicit libpq connection fields and PGPASSFILE are required")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,63}", os.environ["PGDATABASE"]):
        raise BackupError("PGDATABASE must be a plain database name")
    private_file(os.environ["PGPASSFILE"])
    env = tool_environment()
    for key in (*required, "PGSSLMODE", "PGSSLROOTCERT", "PGSSLCERT", "PGSSLKEY", "PGCHANNELBINDING"):
        if key in os.environ:
            env[key] = os.environ[key]
    if env.get("PGSSLKEY"):
        private_file(env["PGSSLKEY"])
    env["PGCONNECT_TIMEOUT"] = "10"
    # TLS policy is explicit; production must use verify-full and a trusted CA.
    if env.get("PGSSLMODE") not in {"verify-full", "disable"}:
        raise BackupError("Set PGSSLMODE=verify-full (disable only for local disposable databases)")
    if env["PGSSLMODE"] == "disable" and env["PGHOST"] not in {"127.0.0.1", "localhost", "::1"}:
        raise BackupError("TLS may only be disabled for loopback")
    return env


def run(command, env=None, stdout=subprocess.DEVNULL, stdin=None):
    try:
        result = subprocess.run(
            command,
            env=env if env is not None else tool_environment(),
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            timeout=1800,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise BackupError("Tool unavailable or operation timed out") from None
    if result.returncode:
        raise BackupError("Operation failed; no success artifact published (tool diagnostics suppressed)")


def gpg(home):
    home = outside_repo(home)
    info = home.stat()
    if not home.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise BackupError("GnuPG home must be owner-only (0700)")
    return ["gpg", "--no-options", "--homedir", str(home), "--batch", "--no-tty"]


def backup(output, home, recipient, work):
    env = environment()
    if not re.fullmatch(r"[0-9A-Fa-f]{40,64}", recipient):
        raise BackupError("Pin the full recipient fingerprint, not a short key ID")
    output = outside_repo(output)
    if output.exists() or not output.name.endswith(".pgdump.gpg"):
        raise BackupError("Use a new .pgdump.gpg output path; existing files are never replaced")
    parent = output.parent.stat()
    if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise BackupError("Output directory must be owner-only (0700)")
    command = gpg(home)
    with tempfile.TemporaryDirectory(prefix="codejudge-backup-", dir=outside_repo(work)) as temp:
        artifact = Path(temp) / "encrypted"
        with artifact.open("xb") as target:
            os.chmod(artifact, 0o600)
            # Dump streams directly to encryption: no plaintext backup file is created.
            try:
                with subprocess.Popen(
                    [
                        "pg_dump",
                        "--no-password",
                        "--format=custom",
                        "--lock-wait-timeout=30s",
                        "--no-owner",
                        "--no-acl",
                    ],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                ) as dump:
                    try:
                        result = subprocess.run(
                            command
                            + [
                                "--trust-model",
                                "always",
                                "--cipher-algo",
                                "AES256",
                                "--force-mdc",
                                "--compress-algo",
                                "none",
                                "--encrypt",
                                "--recipient",
                                recipient,
                                "--output",
                                "-",
                            ],
                            env=tool_environment(),
                            stdin=dump.stdout,
                            stdout=target,
                            stderr=subprocess.DEVNULL,
                            timeout=1800,
                        )
                        dump.stdout.close()
                        code = dump.wait(timeout=30)
                        if result.returncode or code:
                            raise BackupError("Dump or encryption failed; no backup published")
                    finally:
                        if dump.poll() is None:
                            dump.kill()
                            dump.wait()
            except (OSError, subprocess.TimeoutExpired):
                raise BackupError("Dump/encryption unavailable or timed out") from None
            target.flush()
            os.fsync(target.fileno())
        # Hard-link publication is atomic and refuses overwrite/symlink races. Work and
        # output directories must be on the same filesystem; failure leaves no output.
        os.link(artifact, output)
        try:
            directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            output.unlink()
            raise
    print("backup_complete encrypted=true; verify and copy off-host before relying on this backup")


def decrypted(artifact, home, temp):
    artifact = private_file(artifact)
    plain = Path(temp) / "archive"
    # Validate GPG integrity to completion BEFORE parsing/restoring any plaintext.
    with plain.open("xb") as target:
        os.chmod(plain, 0o600)
        run(gpg(home) + ["--decrypt", str(artifact)], stdout=target)
    # Consume archive contents, not merely its table of contents. Never execute SQL.
    with plain.open("rb") as source:
        run(["pg_restore", "--file=/dev/null"], stdin=source)
    return plain


def verify(artifact, home, work):
    with tempfile.TemporaryDirectory(prefix="codejudge-verify-", dir=outside_repo(work)) as temp:
        decrypted(artifact, home, temp)
    print(
        "backup_verified cryptographic_integrity=true archive_readable=true; restoration drill still required"
    )


def restore(artifact, home, work, confirm):
    env = environment()
    # Deliberate safety boundary: this tool cannot restore a production-named DB.
    if confirm != env["PGDATABASE"] or not re.fullmatch(r"[A-Za-z0-9_]+_restore_test", confirm):
        raise BackupError("Restore requires matching --confirm and a dedicated *_restore_test database")
    if env["PGHOST"] not in {"localhost", "127.0.0.1", "::1"}:
        raise BackupError("Restore target must be isolated loopback PostgreSQL")
    with tempfile.TemporaryDirectory(prefix="codejudge-restore-", dir=outside_repo(work)) as temp:
        plain = decrypted(artifact, home, temp)
        # Refuse any existing user objects, including objects outside public schema.
        user_namespace = "n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp%'"
        counts = [
            f"(SELECT count(*) FROM {catalog} o JOIN pg_namespace n ON n.oid=o.{column} WHERE {user_namespace})"
            for catalog, column in (
                ("pg_class", "relnamespace"),
                ("pg_proc", "pronamespace"),
                ("pg_type", "typnamespace"),
            )
        ]
        counts.append(
            f"(SELECT count(*) FROM pg_namespace n WHERE n.nspname <> 'public' AND {user_namespace})"
        )
        query = "SELECT " + " + ".join(counts)

        try:
            result = subprocess.run(
                [
                    "psql",
                    "--no-password",
                    "--no-psqlrc",
                    "--tuples-only",
                    "--no-align",
                    "--set=ON_ERROR_STOP=1",
                    "--command",
                    query,
                ],
                env=env,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise BackupError("Unable to verify empty restore target") from None
        if result.returncode or result.stdout.strip() != b"0":
            raise BackupError("Restore target is not empty or could not be verified")
        with plain.open("rb") as source:
            run(
                [
                    "pg_restore",
                    "--no-password",
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--no-acl",
                    "--dbname",
                    env["PGDATABASE"],
                ],
                env=env,
                stdin=source,
            )
    print(
        "restore_complete atomic=true; verify schema, row counts and application behavior before any cutover"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "verify", "restore"))
    parser.add_argument("--file", required=True)
    parser.add_argument("--gnupg-home", required=True)
    parser.add_argument(
        "--work-dir",
        required=True,
        help="Private scratch outside repository; same filesystem as output for backup",
    )
    parser.add_argument("--recipient")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    try:
        work = outside_repo(args.work_dir)
        info = work.stat()
        if not work.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise BackupError("Work directory must be owner-only (0700)")
        if args.action == "backup":
            backup(args.file, args.gnupg_home, args.recipient or "", work)
        elif args.action == "verify":
            verify(args.file, args.gnupg_home, work)
        else:
            restore(args.file, args.gnupg_home, work, args.confirm)
    except (BackupError, OSError):
        # Never emit libpq errors/URLs, SQL, GPG identities or credential contents.
        print(
            "backup_operation_failed: verify inputs, permissions, tool versions and target safety; no success claimed",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
