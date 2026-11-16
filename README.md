# CodeJudge AI

A Python FastAPI + PostgreSQL backend and Next.js/TypeScript workspace for Python
coding challenges. Phase 3 adds immutable code submissions, versioned stdin/stdout
test suites, structured case results, and a dedicated **gVisor-only** execution
service. API and application workers never execute submitted code.

**Security status:** the local application and fail-closed paths are testable here;
this cloud machine's rootless/ignored-cgroup runtime is deliberately rejected for
untrusted execution. Live sandbox enforcement has not been validated on this host.
Read [runner security and deployment requirements](runner/README.md) before
provisioning execution. No production-grade sandbox security is claimed.

## Local development

Python 3.12, PostgreSQL 16, and Node.js 24 are supported.

```sh
cp .env.example .env
docker compose up --build -d
docker compose ps
cd frontend
cp .env.example .env.local
npm ci
npm run dev
```

The API serves port 8000 (`/docs`), frontend port 3000, database loopback port
55432. Compose applies migrations before starting API/worker and persists data in
a named volume. `docker compose down` retains data; **`docker compose down -v`
deletes it**. Default credentials are local-only fixtures. Never deploy them to
production. Database URL passwords require URL encoding for reserved characters.

No controller or Docker socket is mounted into the application stack. Without a
separately configured, validated runner, evaluations fail with no score.

For native backend development with Compose PostgreSQL:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d db
# .env.example uses localhost:55432
alembic upgrade head
uvicorn app.main:app --reload
# In a second terminal using the same virtualenv/environment:
python -m app.worker
```

Do not run the native and Compose APIs on the same port. Tables are never created
implicitly on API startup. Deploy migrations once before new application replicas;
review generated revisions and back up production before migrating.

## API workflow

All challenge/submission/evaluation/catalog routes require a bearer token and
check ownership. Register with `POST /auth/register`, JSON username (3–64 ASCII
letters/digits/underscores) and password (12–128 characters). Usernames normalize
to lowercase. `POST /auth/token` accepts the same JSON and returns a bearer token,
24-hour expiry by default. `DELETE /auth/token` revokes the current token.
Passwords use salted scrypt; only SHA-256 token digests are stored. The frontend
uses an encrypted HttpOnly session cookie and never exposes the token to browser
JavaScript; see [frontend setup/security](frontend/README.md).

1. `GET /test-suites` returns suite metadata/description and case count, not hidden
   case inputs/expected outputs. Current examples: `sum-two-v1`, `reverse-lines-v1`.
2. `POST /tasks` creates an owned challenge. Supply title, description, max_score
   (1–1000), and `test_suite_id`. The trusted catalog definition is snapshotted in
   the task. Descriptions do not become executable tests. New suite versions need
   new IDs and tasks; public APIs cannot mutate snapshots or install arbitrary tests.
3. `GET /tasks?limit=20&offset=0` lists owned tasks (limit ≤100).
   `GET /tasks/{uuid}` retrieves one.
4. `POST /submissions` with `{"task_id":"UUID","source":"...Python..."}` stores
   an immutable source snapshot and returns its UUID/reference (no source echo).
   Source limit: 16,000 characters and 32 KiB UTF-8, NUL-free. Source is stored as
   data, never imported, compiled or executed by the API. There is no public source
   mutation/download endpoint. Set database retention/encryption/access policies.
5. `POST /evaluations` with `{"task_id":"UUID","submission_reference":"submission UUID"}`
   returns 202 and a durable queued job. Source must belong to this user and task.
   Callers cannot set counts, scores, state, ownership or tests.
6. `GET /evaluations/{uuid}` returns queued/running/succeeded/failed. A completed
   evaluation can have failed cases and score zero; succeeded means grading
   completed, not that all tests passed. `case_results` adds per-case status,
   generic reason and lifecycle duration. Scores/counts remain null until accepted
   results exist. Expected answers and raw stdout/stderr are not exposed.

Strict schemas reject unknown fields, malformed values and oversized source.
Body limit is 128 KiB, including chunked bodies. Validation errors omit rejected
values. Missing/invalid/expired auth returns 401; unauthorized resources appear as
404; invalid payloads return 422; duplicate usernames return 409. Tasks without a
test suite return 409 for code submission/evaluation. `/health` is liveness;
`/ready` checks the current database schema. It does not establish runner health.

## Evaluation and isolation

```mermaid
flowchart LR
  Browser -->|HttpOnly session| Web[Next.js server]
  Web -->|bearer / source snapshot| API[FastAPI]
  API --> DB[(PostgreSQL durable queue)]
  Worker -->|lease + immutable inputs| DB
  Worker -->|authenticated HTTPS| Controller[Dedicated runner host]
  Controller -->|runsc / fresh sandbox per case| Guest[gVisor Python guest]
  Watchdog[Independent deadline watchdog] --> Guest
  Guest -->|bounded stdout| Controller
  Controller -->|compare outside sandbox / journal results| Worker
  Worker -->|fenced result update| DB
```

The runner enforces explicit runsc, verified cgroup controls, non-root identity,
capability removal, read-only root filesystem, no host mounts/devices, no network,
minimal environment, bounded tmpfs and per-case CPU/memory/time/process/output
limits. Before user source is released it verifies container configuration and
actual host cgroups. Signed deployment admission is issued only after adversarial
probes pass on the actual host/image/runtime, and expires after an hour. Missing
or invalid evidence and isolation failures close admission. See the full
[threat model, resource limits and deployment guide](runner/README.md).

The existing durable queue still uses SKIP LOCKED and claim-token fencing. Crashed
leases are reclaimed; stale workers cannot overwrite new attempts. Retryable
network/429/5xx failures are delayed 20s/40s (up to 60s with more attempts).
The controller journals completed results by evaluation UUID and immutable input
hash; mismatched reuse is rejected. Exactly-once execution is not claimed.

Configure only the application worker with `SANDBOX_URL` (HTTPS `/evaluate`),
`SANDBOX_TOKEN`, `SANDBOX_TIMEOUT=75`, `LEASE_SECONDS=180`, and `MAX_ATTEMPTS=3`.
Do not share application database/session credentials with the runner. Never
configure an ordinary Docker runtime as a fallback. Authentication, TLS, patched
runtime/base images, host firewalling, dedicated hosts, watchdog supervision,
node fencing, quotas, monitoring and operational security review remain required.

### Upgrade notes

Phase 3 migrations retain existing data and backfill queue availability timestamps.
Existing tasks have no suite: they remain viewable but cannot execute code. Create
new tasks with an explicit suite. Legacy opaque artifact references do not resolve
to immutable owned submissions and fail closed. Existing completed results remain
readable with `case_results=null`. Existing clients must first upload a source
snapshot via `/submissions`; the frontend implements that flow. The runner contract
is now `python-stdio-v1` with structured cases; counts-only runner responses are
rejected. No automatic migration invents code or test suites for old jobs.

## Tests and CI

```sh
pip install -r requirements-dev.txt
pip check
ruff check .
ruff format --check .
pytest -q --cov=app --cov=runner --cov=contracts --cov-report=term-missing
```

Default tests use disposable SQLite except explicit PostgreSQL concurrency tests.
For the full application/queue suite set `TEST_DATABASE_URL` to a dedicated
PostgreSQL database ending in `_test`; fixtures **drop application tables**.
Never point it at development or production data. With Compose:

```sh
docker compose exec db createdb -U codejudge codejudge_test
TEST_DATABASE_URL=postgresql+psycopg://codejudge:codejudge@localhost:55432/codejudge_test pytest -q
```

`python scripts/smoke.py --restart-api` checks a disposable local Compose stack
with no runner configured. It creates synthetic records and restarts only the
Compose API to verify persistence. Populated migration regression checks use
`DATABASE_URL=<dedicated *_migration_test URL> python -m scripts.validate_migrations`;
that script deliberately resets that dedicated database's schema.

CI runs API/auth/ownership/source/queue tests, runner protocol and security policy
checks (without executing submissions), PostgreSQL concurrency, populated migration
upgrade/downgrade, lint/format/build checks, guest image build, and frontend tests
against a real backend/worker. Full live gVisor tests are a separate, protected,
manual deployment-validation workflow; a skipped live check is not a passed
isolation test. See [runner test interpretation](runner/README.md#test-interpretation).
