# CodeJudge AI

A FastAPI backend with PostgreSQL persistence, SQLAlchemy 2, Alembic migrations,
password authentication, expiring/revocable bearer tokens, and a durable evaluation
queue. Python 3.12 and PostgreSQL 16 are the supported development targets.

## Start locally

```sh
cp .env.example .env
docker compose up --build -d
docker compose ps
docker compose logs api worker
```

Compose starts PostgreSQL, applies migrations once, then starts the API and a
separate queue worker. API and database ports bind only to loopback. Interactive
API documentation is available on port 8000 at `/docs`; `/health` is liveness and
`/ready` checks database/schema availability. PostgreSQL uses a named volume.
`docker compose down` retains data; **`docker compose down -v` deletes it**.
Default database credentials are for local development only. Database passwords
used in `DATABASE_URL` must be URL-encoded when containing reserved characters.

No sandbox is bundled. By default, workers mark jobs `failed` with
`sandbox_not_configured`. This is deliberate: no submitted code is executed by
this repository. Configure a separately secured runner before expecting successful
evaluations. API tests and worker contract tests work without that runner.

For native Python development:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
# Keep PostgreSQL available; the example .env connects to Compose's port 55432.
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
# In another terminal with the same virtualenv and environment:
python -m app.worker
```

Do not run the native API and Compose API on the same port. No tables are created
implicitly at API startup. Run migrations as a deployment step, not in every API
replica. Create future revisions with `alembic revision --autogenerate -m '...'`,
review generated operations, and test upgrades on a backup before deployment.

## Authentication and API

`POST /auth/register` takes JSON `username` (3–64 ASCII letters/digits/underscores)
and `password` (12–128 characters). Usernames are case-insensitive. Passwords are
salted and hashed using scrypt. `POST /auth/token` takes the same JSON and returns
`access_token`, `token_type`, and `expires_in`. Send `Authorization: Bearer TOKEN`
for task/evaluation routes. Tokens expire after 24 hours by default; their SHA-256
digests are stored in PostgreSQL. `DELETE /auth/token` revokes the current token.
There are no default users or embedded application credentials.

Example sequence (use the token returned by `/auth/token`):

```sh
curl -X POST localhost:8000/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"use-a-unique-long-password"}'
curl -X POST localhost:8000/auth/token -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"use-a-unique-long-password"}'
curl -X POST localhost:8000/tasks -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Two Sum","description":"Return indices of two values summing to target.","max_score":100}'
```

- `POST /tasks` → 201; title 3–150 characters, description 10–20,000, max_score 1–1000.
- `GET /tasks?limit=20&offset=0` → caller's tasks; limit is bounded at 100.
- `GET /tasks/{uuid}` → caller's task or 404.
- `POST /evaluations` → 202 with a durable `queued` evaluation. Body:
  `{"task_id":"UUID","submission_reference":"artifact-123"}`.
- `GET /evaluations/{uuid}` → poll status and, when successful, counts/score/feedback.

Artifact references are opaque IDs (1–256 letters, digits, `_`, `-`, `.`; first
character alphanumeric). They are never interpreted as URLs, paths, or commands.
Clients cannot supply test outcomes, scores, ownership, or job state. Unknown
fields, invalid counts/types and malformed UUIDs return 422. Cross-user access
returns 404. Missing/invalid/expired tokens return 401. Duplicate usernames return
409. Request bodies, including chunked bodies, are limited to 128 KiB (413).
Validation responses omit rejected values, including passwords.

**Breaking changes from the prototype:** authentication is required; data survives
restarts; evaluation POST returns 202 instead of 201; caller-reported test results
are rejected; scores remain null until a worker obtains an accepted runner result.
`verified: false` was removed rather than implying this backend independently
verifies runner output. No migration imports the prototype's in-memory data.

## Evaluation architecture and runner contract

```mermaid
flowchart LR
  Client -->|authenticated request| API[FastAPI]
  API -->|atomic durable insert| DB[(PostgreSQL)]
  Worker -->|lease using SKIP LOCKED| DB
  Worker -->|HTTPS / artifact ID| Runner[External isolated runner]
  Runner -->|bounded result JSON| Worker
  Worker -->|fenced result update| DB
  Client -->|poll result| API
```

Only the worker sends requests to the `SANDBOX_URL` operator-configured
endpoint. It does not spawn subprocesses, import submissions, fetch artifact URLs,
or mount a Docker socket. The API creates database jobs and never calls the runner.

Request: POST to `SANDBOX_URL`, optional bearer `SANDBOX_TOKEN`, with
`Idempotency-Key: <evaluation UUID>` and JSON:

```json
{"evaluation_id":"UUID","task_id":"UUID","submission_reference":"artifact-123"}
```

The runner resolves artifact IDs through its own authorized storage and maps task
IDs to **trusted, versioned test suites**. Task descriptions are metadata, not an
executable test specification. A successful response must be 2xx JSON:

```json
{"tests_passed":3,"tests_total":4,"feedback":"Three tests passed."}
```

Counts must be integers, 0 ≤ passed ≤ total ≤ 1,000,000, total > 0; feedback is
limited to 10,000 characters. Unknown fields and malformed/oversized responses are
rejected. Scores use decimal half-up rounding to two places. The runner is part of
the trust boundary: valid result JSON alone does not prove execution correctness.

The external runner is an integration requirement, **not an implemented sandbox**.
Before accepting untrusted submissions it must enforce disposable VM/microVM or
appropriately hardened sandbox isolation, no host/socket mounts, no application
credentials, denied network by default, CPU/memory/process/output/time limits,
trusted immutable tests, and artifact authorization. A plain Docker container
alone is not a sufficient security claim for hostile multitenant code.

Delivery is **at least once**. The runner must deduplicate on evaluation UUID and
return stable results across retries. `FOR UPDATE SKIP LOCKED` claims one job
transactionally, then releases the DB connection before network evaluation.
Expired leases are reclaimed. Claim tokens fence late/stale writes. HTTP 429/5xx
and transport errors retry up to `MAX_ATTEMPTS`; other HTTP errors, invalid results,
and missing runner configuration fail closed. Crashed attempts count toward the
limit. Polling has a one-second delay between jobs/retries; there is no callback
endpoint or public result-injection route. Failed jobs are terminal; submit a new
evaluation after fixing configuration.

## Configuration and operations

See `.env.example`. Settings also accept process environment variables:

| Setting | Default | Purpose |
| --- | --- | --- |
| DATABASE_URL | local PostgreSQL on 5432 | SQLAlchemy psycopg URL; `.env.example` uses 55432 |
| TOKEN_HOURS | 24 | Token lifetime, 1–720 hours |
| SANDBOX_URL | unset | Operator-controlled HTTPS evaluation endpoint |
| SANDBOX_TOKEN | unset | Runner bearer credential; inject via secret manager |
| SANDBOX_TIMEOUT | 30 | Network timeout, 1–120 seconds |
| LEASE_SECONDS | 180 | Job lease, 150–3600 seconds |
| MAX_ATTEMPTS | 3 | Attempt limit, 1–10 |
| ALLOW_INSECURE_SANDBOX | false | Explicit HTTP override for local runner testing only |

HTTP redirects are never followed and TLS certificate verification stays enabled.
The worker uses direct networking rather than ambient proxy variables; provision
its approved runner network route explicitly. Keep runner endpoints on an egress
allowlist and credentials away from API containers. Do not expose `.env`, bearer
tokens, sandbox request/response payloads or SQL parameters in logs. Worker logs
include job IDs/attempt numbers and sanitized errors.

Before an Internet-facing deployment, supply TLS termination, shared gateway rate
limits (especially registration/login and evaluation submission), request/read
limits and connection timeouts, trusted proxy configuration, secret rotation,
PostgreSQL TLS/backups/restore drills, observability, and retention policies for
expired tokens and completed jobs. `/health` does not imply workers are healthy;
monitor oldest queued job age, expired leases, failures, DB pool saturation and
worker process availability. Configure service roles/least-privilege database
permissions and isolate the runner network from API/database networks. Disable
public registration or replace it with organizational identity if required.
Containers run as a non-root user; Compose drops capabilities and uses a read-only
application filesystem. Compose is a local development topology, not a production
deployment manifest.

## Tests and checks

```sh
pip install -r requirements-dev.txt
pip check
ruff check .
ruff format --check .
pytest -q --cov=app --cov-report=term-missing
```

Exact tested dependency versions are recorded in `constraints.txt` and applied by
`requirements.txt`; update constraints deliberately and rerun checks when upgrading.

The default suite uses disposable SQLite databases for fast API/worker tests.
PostgreSQL is mandatory for queue concurrency guarantees. Run the full suite
against a **dedicated disposable test database** (the fixture drops all application
tables and requires a database name ending in `_test`; never point this at
development or production data):

```sh
# With Compose's local database running:
docker compose exec db createdb -U codejudge codejudge_test
export TEST_DATABASE_URL=postgresql+psycopg://codejudge:codejudge@localhost:55432/codejudge_test
pytest -q --cov=app --cov-report=term-missing --cov-fail-under=85
```

For a disposable local Compose stack with no runner configured,
`python scripts/smoke.py --restart-api` checks the authenticated API, fail-closed
worker, token revocation, and persistence across an API restart. It creates test
records and restarts only the Compose API.

CI uses PostgreSQL 16, tests migration upgrade/downgrade and schema drift, lint and
format checks, dependency consistency, ≥85% application coverage, and builds the
production image and runs the Compose smoke workflow. Tests cover authentication/expiry/revocation, owner isolation,
validation, durable queue transitions, bounded retries, invalid runner output,
crash recovery, stale writes, and real PostgreSQL concurrent/locked claims. Runner
responses in tests are simulated; live hostile-code sandboxing is not claimed.
