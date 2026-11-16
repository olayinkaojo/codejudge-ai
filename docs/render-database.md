# Render PostgreSQL readiness and migrations (Phase 5A)

This fix targets the existing free `codejudge-api` web service and `codejudge-db`
database. It does not create services, upgrade plans, enable execution workers,
merge Phase 3, or change any production setting automatically. Apply the deployment
steps below **only after reviewing and approving the code and configuration**.

## Findings: confirmed versus unconfirmed

Confirmed by repository inspection and local verification:

- The previous Docker CMD launched Uvicorn directly. It contained no migration
  step. Local Compose has a separate migration service, but that does not mean
  Render runs that Compose service or applies migrations.
- The installed driver is Psycopg 3 (`psycopg[binary]`). SQLAlchemy normally treats
  bare `postgresql://` as its default Psycopg 2 dialect, and legacy `postgres://`
  is not the installed dialect. The previous configuration did not normalize
  those URL schemes. The fix normalizes both to `postgresql+psycopg://`, retaining
  parsed credentials, database, host and TLS/query options. Explicit unsupported
  drivers are rejected safely.
- The previous readiness check selected from `users` only and discarded database
  error details. It could not establish that other tables/columns or the deployed
  Alembic revision were ready.
- A fresh disposable PostgreSQL database is unready before migration. The upgrade
  command creates the expected schema; rerunning it preserves inserted records.
  Alembic's model comparison reports no pending schema changes afterward.

**The live production root cause is not confirmed.** This task environment's
outbound proxy blocked read-only requests to the Render URLs (and Render's docs).
No live database URL, credentials, Render logs, runtime command or database schema
was available to inspect. Missing migrations, an incompatible URL scheme, wrong
credentials/database, DNS/connectivity/TLS, and schema drift remain hypotheses
until the safe diagnostic category from the deployed service is observed. Do not
interpret a running Render database or `/health` 200 as proof of schema readiness.

No production success is claimed. The acceptance check is the live `/ready`
endpoint **after your reviewed deployment and migration**.

## Files and responsibilities

| File | Why it changed |
| --- | --- |
| `app/config.py` | Normalize Render-style PostgreSQL schemes to Psycopg 3; suppress secret input values in configuration errors/repr. |
| `app/db.py` | Share an engine factory, hide SQL parameters, bound connection/pool waits, and safely report engine/driver initialization failures. |
| `app/database_status.py` | Read-only table/column/revision checks and allowlisted diagnostic categories without raw exceptions or URLs. |
| `app/main.py` | Stronger readiness, generic public 503s, safe database error handling; liveness remains independent. |
| `app/migrate.py` | Controlled, locked, upgrade-only migration with post-upgrade readiness verification and safe failure logging. |
| `app/start.py`, `Dockerfile` | Explicit migration opt-in before server startup, using Render's PORT and normal start command rather than a paid shell/job/pre-deploy feature. |
| `migrations/env.py`, `alembic.ini` | Reuse the locked connection and shared driver configuration; use reliable migration paths. No migration revision or production data model is changed. |
| `tests/`, `.github/workflows/ci.yml` | Verify redaction, unavailable/missing/version-mismatched databases, startup failure behavior, real PostgreSQL upgrades, repeatability, locking and model compatibility. |

## How the migration mechanism works

The new image CMD is `python -m app.start`.

- Default `MIGRATE_ON_START=false`: launch the API without migrating, preserving
  an explicit operator choice. `/ready` stays 503 if the database/schema is wrong.
- With `MIGRATE_ON_START=true`: acquire a PostgreSQL session advisory lock, run
  the equivalent of `alembic upgrade head`, verify required schema and revision,
  then exec Uvicorn. If any step fails, exit nonzero **before starting the API**.
- Actual DDL is applied once per pending revision; subsequent starts only perform
  Alembic's already-applied check and validation. Nothing migrates on API requests.
- Concurrent starts serialize with a bounded lock wait (30 seconds). PostgreSQL
  DDL lock waits are limited to 5 seconds, migration statements to 120 seconds.
  Failed transactional upgrades roll back; no automatic stamping, downgrading,
  drop, reset, recreation, or deletion is performed.
- Connection/pool acquisition waits are bounded. The engine defaults to a
  5-second connection timeout. TLS options from the supplied URL are preserved;
  this fix does not disable certificate verification or weaken SSL settings.

This uses the ordinary web-process startup path, which does not require a paid
Render shell, worker, cron service, or pre-deploy command. Do not configure a paid
feature as a substitute. Keep the existing service/database and plan.

Leaving the flag true is appropriate for **reviewed** future migration releases:
restarts do not rerun already-applied DDL. If your policy requires a one-time
bootstrap window, set it false after successful verification; you must explicitly
re-enable it for a later reviewed migration release. Do not forget that step.

## Deployment instructions — after your approval

1. Review the PR/compare against `main` and approve this release. Do not merge
   `feature/isolated-python-evaluation` or PR #3 as part of this fix.
   If Render auto-deploys on merge and you need a controlled rollout, pause that
   existing service's auto-deploy setting first, with your approval. Then merge
   this fix yourself and confirm its commit is on `main`.
2. In Render, open the **existing** `codejudge-db` page. Confirm it is available
   and inspect any plan/expiry/connection warnings privately. Do not recreate it.
   For services in the same region, use its supplied **Internal Database URL**.
   Copy it only into Render's secure environment-variable editor, never chat,
   GitHub, source code, a screenshot or a log.
3. Open **existing** `codejudge-api` → environment/settings. Verify:

   | Setting | Value/action |
   | --- | --- |
   | `DATABASE_URL` | Existing valid database URL from `codejudge-db`; retain authentication and provider TLS options. `postgres://`, `postgresql://`, and `postgresql+psycopg://` are supported. |
   | `MIGRATE_ON_START` | Set `true` for this reviewed migration deployment. This is new and opt-in. |
   | `PORT` | Let Render supply it; the startup wrapper uses it (8000 fallback locally). |
   | `SANDBOX_URL` | Keep unset/empty; do not enable the unvalidated Phase 3 runner. No additional worker is required for this database fix. |

   Keep unrelated existing settings/secrets unchanged. Do not add database secrets
   to Vercel; only the backend uses PostgreSQL directly.
4. Confirm the startup path. For an existing **Docker** service, use the repository
   root/Dockerfile. Leave the Docker Command override empty to use the new CMD,
   **or** set it to `python -m app.start`. An old `uvicorn ...` override bypasses
   the migration wrapper and must not be left in place for this deployment.
   For an existing **native Python** service, keep its working build setup and
   Python 3.12 environment; set its ordinary **Start Command** to
   `python -m app.start` from the repository root. Do not create a replacement
   service or change runtimes/plans just to obtain a shell.
5. Deploy the latest approved `main` commit using that service's normal manual
   deploy action. Do not use a paid pre-deploy field or a public migration URL.
   No HTTP endpoint is provided to trigger migrations.
6. Watch the service's normal deployment logs. A successful startup contains
   `database_migrations_complete schema=ready`, followed by Uvicorn startup.
   This message is emitted only after the expected tables/columns and Alembic
   revision pass verification. Verify the dashboard's deployed commit as well;
   an old `/health` response alone does not identify the new release.
7. Verify the public endpoints (Render Free can need time to wake):

   ```sh
   curl --fail --show-error --max-time 60 https://codejudge-api-enru.onrender.com/health
   curl --fail --show-error --max-time 60 https://codejudge-api-enru.onrender.com/ready
   ```

   Required responses are HTTP 200 with `{"status":"ok"}` and
   `{"status":"ready"}`, respectively. A timeout or any 503 is not success.
   After confirming the rollout, `/ready` is the recommended Render Health Check
   Path if you approve updating that setting. It reads database state only.
8. Open https://codejudge-ai-eta.vercel.app. Privately register one approved test
   account, then sign in and open the challenge dashboard. Empty task data is a
   valid new-account result. Do not paste passwords or bearer/session tokens into
   chat or issue bodies. Registration creates a normal user record; no production
   registration was attempted by the agent.
9. No Vercel code deployment or database credential is needed for this fix. If
   frontend auth still fails after live readiness passes, privately verify its
   existing server-only `BACKEND_URL` is `https://codejudge-api-enru.onrender.com`,
   `APP_ORIGIN` matches `https://codejudge-ai-eta.vercel.app`, and its existing
   `SESSION_PASSWORD` is valid. Do not rotate or change these without approval.
   Do not put any of them under `NEXT_PUBLIC_`. Frontend errors can be separate
   from database readiness; inspect safe status messages before changing settings.

## Failure diagnostics and recovery

Public responses remain `503 {"detail":"Database unavailable"}`. Server logs add
only `operation`, a fixed category, and SQLSTATE when available. They never print
raw exception text, database URL, password, SQL parameters or arbitrary provider
messages. Example: `database_operation_failed operation=readiness
category=schema_missing sqlstate=42P01`.

| Category | Next action |
| --- | --- |
| `schema_missing` | Confirm the new startup wrapper actually ran with the flag true and the correct database binding. Missing columns with an already-current revision can indicate drift; review rather than resetting. |
| `schema_version_missing` | Tables may exist without migration history. Do not blindly stamp. Request a reviewed baseline/adoption plan and backup. |
| `schema_version_mismatch` | Database and deployed release disagree. Deploy compatible reviewed code; do not stamp/downgrade or merge Phase 3 to silence the check. |
| `schema_conflict` | An upgrade met existing objects, often an unstamped/partial legacy schema. Stop and review; no drop/recreation workaround. |
| `authentication_failed` | Recheck the secure Render URL binding against the existing database's current credentials. Never post the value. |
| `dns_failure`, `connection_unavailable` | Check the supplied internal/external URL choice, region, database availability, service connectivity and provider status. Do not replace the DB or upgrade the plan reflexively. |
| `database_not_found` | Confirm the URL selects the existing `codejudge-db` database. |
| `permission_denied` | Confirm the intended database owner/migration role is used; do not grant broad privileges automatically. |
| `migration_lock_timeout`, `database_timeout` | Another migration/lock or an overloaded database may be active. Inspect deployments, wait for completion and retry the reviewed deployment. Do not force-clear locks or remove safety timeouts to hide a problem. |
| `configuration_error`, `driver_unavailable`, `migration_configuration_error` | Check deployment commit, supported URL scheme/driver, root working directory, dependency install, and included Alembic files. |
| `database_error` | Cause remains unknown (including possible TLS errors). Use the safe category/SQLSTATE and deployment metadata for further diagnosis. Do not disable TLS or dump environment/credentials/raw database exceptions into chat. |

If migration startup fails, the new API process deliberately does not launch. Do
not bypass the wrapper merely to make a deploy appear green. Correct the identified
configuration/availability problem and retry. The current initial migration only
creates schema; no revision was rewritten and no destructive migration was added.
Take a provider-supported backup before production schema work where available;
this task does not assume paid backup/shell features or authorize an upgrade.
Rolling application code back is not permission to run `alembic downgrade` against
production. Never use `Base.metadata.create_all`, `alembic stamp`, schema reset or
manual table deletion as an improvised production repair.

## Local/CI verification

The ordinary Python suite exercises safe diagnostics/readiness/startup behavior.
PostgreSQL integration additionally verifies upgrade, repeat execution with row
preservation, advisory-lock refusal, and Alembic model compatibility. Use only
explicitly disposable `_test` / `_migration_test` databases; the existing unit-test
fixtures recreate application test tables. The migration integration itself is
upgrade-only and never drops a schema.

```sh
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
# Supply local disposable database bindings; never production values:
TEST_DATABASE_URL="$LOCAL_TEST_DATABASE_URL" \
MIGRATION_TEST_DATABASE_URL="$LOCAL_MIGRATION_TEST_DATABASE_URL" \
python -m pytest -q
```

No Phase 3 migration or runtime is included, and no production deployment or
configuration change is performed by these instructions until you approve and
execute the relevant steps.
