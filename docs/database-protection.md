# PostgreSQL backups, recovery drills and Free-tier expiry

Based on main `2c585fc`, Phase 6B adds `scripts/db_backup.py`, an operator-only Python standard-library CLI
using **pg_dump, pg_restore, psql and GnuPG**. It runs on an existing trusted
computer, not in the Render API, a paid worker, or a scheduled GitHub production
job. No production secrets/data were read, downloaded, backed up or restored during
implementation. Automated drills create synthetic loopback databases only.

## Audit and guarantees

The application uses PostgreSQL 16/Psycopg 3, SQLAlchemy and upgrade-only startup
migration coordination. The initial revision `00391b88d2bb` and Phase 4 revision
`b5cbbc4049b7` remain unchanged. New additive revision `f6b20261116` creates only
authentication admission tables. No migration deletes or rewrites users, passwords,
tokens, tasks, reviews or evaluations. Apply this revision only in a separately
approved deployment. `/ready` requires the matching revision and table columns.

The backup is a consistent custom-format PostgreSQL logical dump, streamed directly
into AES256 OpenPGP encryption with an integrity check. Dump AND encryption must
succeed; a failed pipeline never publishes a success file. The encrypted temporary
file is fsynced and atomically linked to a new destination (never overwrite).
Work/output must share a filesystem. This is a logical backup, not WAL/PITR,
a cluster/role backup, or a managed availability guarantee. Ownership and ACLs are
omitted deliberately; restore privileges must be reviewed separately.

Verification decrypts completely and validates OpenPGP integrity **before** parsing
all archive contents with `pg_restore --file=/dev/null`, without a DB connection.
Encryption detects corruption but does **not** establish who produced a file:
anyone with a public recipient key can encrypt another archive. Keep its SHA-256
and provenance in a trusted independent inventory, or use a separately reviewed
signing process. Restore only trusted backups; database archives can contain SQL
functions/extensions. Verification alone is not proof of restorability.

The restore command is intentionally limited to explicitly confirmed, empty,
loopback databases named `*_restore_test`. It never uses `--clean`, drops databases,
or replaces existing tables/data. `pg_restore --single-transaction --exit-on-error`
rolls SQL changes back on failure. The target must be newly provisioned and isolated
from applications/other writers; the empty-target preflight is not a lock against
an unrelated administrator changing that DB concurrently.

## Prerequisites and key management

Use PostgreSQL client tools matching the server's major version (16 here) and
GnuPG. A newer client's output may not restore to an older server. No new Python
packages or hosted services are required. On a supported development/CI Ubuntu
host, install the free PostgreSQL 16 client and GnuPG through its package manager.

Use a dedicated GnuPG home outside the checkout, mode 0700, containing the public
recipient key. Pin its **full fingerprint**, verified independently. The backup
machine needs only the public key; keep the private recovery key on a different
existing secure/offline device, with a separately protected passphrase and recovery
instructions. Import/export keys outside git. Do not put private keys or passphrases
in command arguments, application settings, GitHub secrets/artifacts or this repo.
A missing/wrong/expired recipient key causes backup failure, not plaintext fallback.
The unprotected short-lived test key is synthetic and is not a production example.

Use a private output directory and private work directory (0700), both outside the
repository. Backups are 0600. Verification/restore temporarily materialize plaintext
in a private 0700 directory with a 0600 archive, removed on normal completion/error.
Use an existing encrypted filesystem or adequately sized tmpfs for this scratch.
Crashes/SIGKILL/power failure can leave scratch files; cleanup must be included in
the operator procedure. Unlinking is not guaranteed secure erasure on SSDs/backups.
Never run these tools on an untrusted shared machine or use public CI for real data.

## Explicit connection configuration

The CLI never loads `.env`, DATABASE_URL, service defaults or application settings.
Supply explicit libpq environment variables `PGHOST`, `PGPORT`, `PGDATABASE`,
`PGUSER`, `PGPASSFILE` and `PGSSLMODE`. PGDATABASE must be a plain database name.
PGPASSFILE must be an owner-only regular file outside the repo; edit it privately
using libpq's `hostname:port:database:username:password` syntax and escaping rules.
Do not paste credentials into a command, ticket or terminal output. PGPASSWORD,
PGSERVICE/PGSERVICEFILE, PGOPTIONS and unrelated application secrets are not passed
to child processes. Optional client TLS private keys must also be owner-only and
outside the checkout.

Remote backups require `PGSSLMODE=verify-full` and a trusted CA, for example the
operator's system CA bundle via PGSSLROOTCERT. Verify Render's current certificate
chain/hostname requirements. TLS disable is accepted only for loopback synthetic
DBs. There is a 10-second connection timeout, 30-second dump-lock wait, bounded
subprocess execution, no shell interpolation and suppressed raw tool errors (which
can contain connection/user details). Failure returns a nonzero exit code and a
safe category; no success is claimed. Troubleshoot permissions/client versions and
service health privately, without enabling password/body/debug logging.

## Backup and verification procedure

After an authorized operator has set the private libpq environment, examples below
contain **paths and a public fingerprint placeholder only**, no live credentials:

```sh
umask 077
python scripts/db_backup.py backup \
  --file /secure/codejudge-backups/reviewed-utc-timestamp.pgdump.gpg \
  --gnupg-home /secure/codejudge-public-keys \
  --recipient FULL_VERIFIED_RECIPIENT_FINGERPRINT \
  --work-dir /secure/codejudge-backups/work
sha256sum /secure/codejudge-backups/reviewed-utc-timestamp.pgdump.gpg
```

Copy the encrypted file to an existing **off-host** computer/disk under your
control. Keeping it beside the source DB or only on Render's ephemeral filesystem
is not protection. Verify transfer checksum against the trusted inventory. On the
separate recovery machine with the privately unlocked recovery key:

```sh
python scripts/db_backup.py verify \
  --file /secure/codejudge-backups/reviewed-utc-timestamp.pgdump.gpg \
  --gnupg-home /secure/codejudge-recovery-keys \
  --work-dir /secure/codejudge-recovery-work
```

No private-key unlock/passphrase is automated by this script. Unlock through the
trusted machine's GnuPG agent beforehand. A checksum and a successful process exit
are not substitutes for the restore drill below. Keep the original encrypted copy
until a replacement has been verified and restored successfully.

## Isolated restore drill

Create a **new disposable local PostgreSQL database** on an isolated instance; do
not reuse the application's development, staging or production database. Set the
explicit libpq environment to this loopback target, whose name ends `_restore_test`.
Then:

```sh
python scripts/db_backup.py restore \
  --file /secure/codejudge-backups/reviewed-utc-timestamp.pgdump.gpg \
  --gnupg-home /secure/codejudge-recovery-keys \
  --work-dir /secure/codejudge-recovery-work \
  --confirm codejudge_drill_restore_test
```

The confirmation must exactly match PGDATABASE. Restore does not create the DB,
reset it, grant permissions or bypass the guard for a production-named target.
Check row counts, owner relationships, UUIDs, JSON results, timestamps, password
hashes, token policy and `alembic_version`. Compare with a trusted source inventory.
Run `/ready` and authenticated read-only API checks against this isolated copy;
keep all external integrations and execution workers disabled. Never log restored
user rows/password hashes or expose the drill database publicly. Dispose of only
the explicitly created drill DB after validation, following local data policy.

Automated tests generate fresh synthetic databases, an ephemeral test GPG key, and
rows for users, tokens, tasks, evaluations and mock reviews. They prove encrypted
backup, offline verification, restored authentication/readiness, IDs/password hashes/
JSON preservation, and refusal of tampered/wrong-key/invalid archives, overwrite,
nonempty targets, nonexistent source DBs and unsafe target names. They never use
production connections or upload backup/key artifacts. CI installs free client
utilities and performs this drill against its disposable PostgreSQL service.

## Frequency, retention and free-tier limits

Proposed operator policy: daily encrypted backup, plus before a migration or an
expiry/cutover; verify every copy and run a restore drill at least monthly and
before a cutover. Keep 7 daily, 4 weekly and 3 monthly **verified** copies if existing
storage allows, with at least two independent off-host copies and a separate key
recovery copy. Record UTC backup/verification/drill times, DB/server/client versions,
revision, checksum, destination and exit status, not row data or secrets.
Do not delete the last verified copy because a new backup job merely started.
Apply privacy retention to encrypted copies too: they include password hashes,
token digests, review fragments and auth privacy-key/counter state.

An existing always-on trusted computer can run the command using cron/systemd and
a private environment file that contains PG connection fields/passfile path, not
an inline password. Require nonzero-exit monitoring by an operator and periodic
manual recovery checks. No scheduler, alert service, storage account, GitHub
production credential, or paid service is provisioned by this change. If that
computer is off/asleep or storage is full, the backup does not happen. Without
an operator-owned scheduler/monitor there is no automatic daily-backup guarantee.
A daily policy permits roughly a day's data loss, potentially longer after missed
jobs; recovery time depends on available hardware, network and manual work.
Free-tier DB snapshots, PITR, indefinite retention and uninterrupted replacement
capacity are **not** assumed.

## Render Free expiration / migration runbook

1. In the Render dashboard, record the **actual current expiry date**, lifecycle,
   grace/recovery rules, storage limits and supported backup options. Free
   PostgreSQL offerings can be time-limited and policies change; do not assume a
   permanent free DB or rely on a historical grace period. Consult current
   [Render Free service docs](https://render.com/docs/free) and
   [PostgreSQL backup docs](https://render.com/docs/postgresql-backups).
2. Well before that date, export an encrypted backup over the approved external
   TLS connection from an existing trusted machine. Copy it off-host, verify its
   checksum and restore it into an isolated local drill DB. Record the tested
   application revision and data inventory. Never wait until expiration to test
   whether export still works.
3. Obtain explicit approval for any live cutover. Plan a write-maintenance window
   and a final consistent backup; without pausing writes, updates after the dump's
   snapshot will be absent from a restored copy. Do not delete/reset the original
   DB or discard earlier verified backups to make room for a replacement.
4. Identify an approved empty replacement within actual zero-cost capacity. A free
   plan may restrict the number/lifetime of DBs; this code does not bypass limits,
   open paid accounts, or promise a free replacement. If no supported replacement
   exists, retain the encrypted/offline recovery copies and keep the application
   safely unavailable/read-only until an approved destination exists.
5. Restore and validate the final backup on a fresh isolated copy first. A later
   **production** import/cutover is a separate operator-approved procedure with
   standard pg_restore, least privileges, TLS and reviewed target identity. The
   supplied restore CLI intentionally cannot perform that live import. Never
   weaken its guards or point automated tests at a production DB to save time.
6. After separately approved import/configuration, confirm revision/readiness,
   counts/ownership and login/session policy before reopening writes. Changes to
   production credentials/origins/secrets require separate approval and are not
   performed here. Restored tokens may reflect the backup's older revocation state;
   review whether to revoke sessions during recovery. Keep the original and final
   backups until acceptance; do not silently switch to an older, divergent writable
   database as a rollback.

A backup can recover exported data after provider loss; it cannot extend the Free
DB's lifetime or recover writes made after the last valid snapshot. If access has
already expired, use only provider-supported recovery options with approval and
restore the last verified external backup. No recovery promise is made for data
that was never exported successfully.


## Validation recorded for this branch

Local validation on 2026-11-16: 132 Python tests passed with 95.12% application
coverage, 42 frontend tests passed and 6 desktop/tablet/mobile journeys passed.
Ruff, ESLint, Prettier, types, Next.js production build, dependency consistency,
migration/model checks and separate local Docker restart-persistence smoke passed.
The native PostgreSQL client commands in this managed workspace were supplied by
thin local wrappers around an isolated PostgreSQL 16 container; CI installs native
16 clients. Both use the same CLI and actual pg_dump/pg_restore/GnuPG operations.
No production connection/data, backup schedule, paid storage or real AI call was
used. Remote CI and live recovery readiness must be checked separately.
