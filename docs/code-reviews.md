# Phase 4: private, text-only Python reviews

This feature is based on main `6b70d6c` (including Phase 5A). The default is a
**simulated mock**, not a validated real AI service. No submitted code is executed,
imported, evaluated, dynamically loaded, or sent to an execution runner. No paid
service/account is provisioned. Production settings and data are unchanged.

## Request and storage flow

1. The existing encrypted HttpOnly session protects the Next.js BFF. Its bearer
   token stays on the server. Mutation origin checks and route allowlists apply.
2. FastAPI authenticates, validates Python text (16,000 characters AND 32,768 UTF-8
   bytes, nonempty, no NUL; CRLF/CR normalized to LF), and checks optional task ownership. Unknown fields are
   rejected, as are non-boolean consent values.
3. PostgreSQL transaction-scoped advisory lock `732347850136` serializes budget
   reservation across API replicas. Counts include every reserved request, including
   failures and interrupted work. Lock wait is bounded to two seconds; database
   failure returns a safe 503 and makes no provider call.
4. A `processing` record commits **before** provider work. No source text is stored:
   a SHA-256 digest and line count identify the snapshot, with owner, optional task,
   provider, timestamps, deadline, status, structured result and safe error category.
5. The bounded provider runs within the request. The API returns 201 with a
   completed or failed review; clients must inspect `status`, not infer success from
   HTTP status. No background task/paid worker/queue is needed. Provider work has no
   automatic retries. Each explicit repeat creates a new charged usage reservation.
6. Completion uses a conditional update requiring `processing` and an unexpired
   20-second deadline. A late response cannot overwrite interruption/failure. List
   and detail reads mark this owner's overdue processing records failed. An idle
   interrupted record may remain processing in storage until that owner next reads
   history; no request is silently restarted after a process crash.

This processing model favors bounded work and durable records on Render Free.
A cold start or the BFF's 10-second timeout can leave an uncertain POST outcome.
Check history before manually retrying. A provider might have charged even if the
request failed or its result was discarded; no exactly-once billing is claimed.

## API contracts

All endpoints require the existing bearer authentication, including configuration.
Responses and the BFF use `Cache-Control: no-store`.

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/reviews/config` | Provider, external disclosure flag, availability, source limits, retention and daily limit. Never keys. |
| POST | `/reviews` | `{ "source": "def solve():\n    pass\n", "language": "python", "task_id": "optional-owned-task-UUID", "external_consent": false }`. Omit task_id if unrelated. 201 persisted result; 422 invalid/consent required, 404 foreign/missing task, 429 usage cap, 503 disabled external provider/database failure. |
| GET | `/reviews/{uuid}` | Owner-only record or 404, including expired records. |
| GET | `/reviews?limit=20&offset=0` | Own unexpired records, newest first, stable created/id ordering; limit 1–100, offset 0–10,000. |

Review fields: id, optional task_id, language, provider (`mock`/`openai`), status
(`processing`/`completed`/`failed`), nullable result/error, created_at, completed_at,
expires_at. Internal source digests and ownership are not returned. Findings contain
severity (`info`/`warning`/`critical`), title, nullable 1-based line, evidence
(`text_pattern`/`speculative`), explanation, suggestion and optional snippet. Results
also contain summary, positive observations and limitations. No execution outcomes,
scores, tests passed, or measured performance fields exist.

## Providers and limits

`app.review_provider.review` is the dispatcher boundary. The default provider uses
bounded regex text patterns for broad exception handlers, dynamic execution-like
calls, console output, unfinished work, naming, line length, mutable defaults,
shell invocation and nested iteration. It does not parse Python syntax and can
match comments/strings. Its observations are useful demonstration hints, not a
comprehensive static analyzer or AI-generated proof of correctness.

The optional OpenAI adapter uses a fixed HTTPS chat-completions endpoint, no
redirects, no tools, no retries, and an asynchronous HTTP client under an overall
`asyncio.timeout`. It separates system instructions from untrusted source. Prompt
injection cannot invoke tools or execution because none are provided. A model may
still follow hostile text or produce bad advice; prompt instructions do not prove
semantic safety. Every model finding is forced to `speculative` evidence.

Response consumption is capped at 32 KiB, compressed responses are rejected,
structured output disallows extra fields, and truncated/invalid JSON is rejected.
Findings are capped at 12, positives at 5, limitations at 5, snippets at 1,500
characters and individual text fields are bounded. Out-of-range lines fail
validation; plausible but incorrect model line references remain unverified.
React escapes all fields and snippets. No unsafe HTML, markdown execution, source
imports, subprocess calls, or runner integration is used.

| FastAPI variable | Default | Bounds / purpose |
| --- | --- | --- |
| `REVIEW_PROVIDER` | `mock` | Only `mock` or `openai`. |
| `REVIEW_EXTERNAL_ENABLED` | `false` | Must explicitly be true for real calls. |
| `REVIEW_API_KEY` | unset | Backend secret only; never `NEXT_PUBLIC_*`, logs, git or browser. |
| `REVIEW_MODEL` | `gpt-4.1-mini` | Operator-controlled bounded identifier; verify API/model compatibility before future activation. |
| `REVIEW_TIMEOUT` | `5` | 1–6 seconds overall external HTTP deadline. |
| `REVIEW_MAX_OUTPUT_TOKENS` | `1200` | 128–2,000 completion-token ceiling. |
| `REVIEW_USER_DAILY_LIMIT` | `20` | 1–100 reservations/user/UTC day; also hard limit 3/user/rolling minute. |
| `REVIEW_GLOBAL_DAILY_LIMIT` | `200` | 1–1,000 reservations/UTC day across all users/providers/replicas. |

There is no per-request provider selector or arbitrary URL. Even after an operator
opts in, each external POST requires `external_consent: true`. The frontend displays
where source goes and requires a checkbox. No real provider calls have been made
for validation; all adapter tests use HTTPX MockTransport, including timeout,
malformed, oversized, truncated and redirected responses. Model quality, latency,
compatibility and current pricing have **not** been validated live.

Input bytes, output tokens, request counts and no retries bound consumption, but
these are not a dollar budget. Before a separately approved future activation,
check provider pricing (including any reasoning-token rules), set a provider/project
spend cap, review privacy/retention terms, choose conservative global limits and
monitor usage. A third-party free tier is not assumed. Compose and CI explicitly
force mock mode. Native mock use needs no key and makes no external AI calls.
SQLite is a unit-test convenience; external requests fail closed outside PostgreSQL.

## Privacy and retention

Source is transient request memory only. It is not persisted or logged by the
application. The browser draft stays in memory, not local/session storage. Provider
prompts, responses and exception text are not logged. Do not enable HTTP body/debug
logging or third-party tracing that captures bodies; infrastructure log policies
must be reviewed separately. A source digest is an identifier, not encryption.

Review text and suggested snippets may contain fragments of private source or user
secrets. They are stored as ordinary PostgreSQL JSON with owner checks, not field-
encrypted data. Protect DB access, backups and transport using the existing managed
PostgreSQL controls. Never submit secrets. With external opt-in, the complete source
is sent to the provider, whose retention policies cannot be controlled by this app.

The access window is 30 days: expired results always return 404 and are excluded
from history. Every creation physically deletes up to 100 expired records globally.
This is opportunistic cleanup, **not a guaranteed 30-day physical deletion SLA**:
inactivity or backups may retain expired data longer. If a deletion deadline is
required, an operator must arrange reviewed maintenance and backup expiry; e.g. a
bounded transactional DELETE selecting expired IDs, repeated until clear. Do not
schedule infrastructure or change production settings without separate approval.
No raw source remains in a record waiting for cleanup.

## Local checks and deployment review

No production migration is run by this change. For a dedicated local database,
install the existing Python and frontend dependencies, run `python -m app.migrate`,
start the API and Next.js, then register/sign in, create a challenge, and Review code.
The execution worker is unnecessary for reviews. `/ready` checks the new table and
revision; `/health`, login and existing task/evaluation contracts remain intact.

CI uses PostgreSQL, upgrades/downgrades only disposable databases, checks model
schema drift and runs the full Python suite with >=85% coverage. It also runs Ruff,
dependency checks, Docker/Compose smoke, frontend lint/format/unit/build/type checks,
and Chromium desktop/mobile browser flows. The browser flow persists a mock review
across reload, verifies provider labels and line references, checks storage/privacy
and mobile overflow, and preserves honest runner-unconfigured evaluation failure.
Security tests cover ownership, source/pagination bounds, deterministic nonexecution,
prompt separation, malicious HTML escaping, provider failure/timeout, durable usage
reservation, concurrent budgets, stale completion and expired result access.

After review/merge approval, deployment order is additive migration then backend,
then frontend. Existing Phase 5A migration startup can perform the upgrade only
when its explicit `MIGRATE_ON_START` setting is enabled. Leave real-provider settings
off and Phase 3 runner disabled. Verify `/ready`, registration/login, a mock review,
owner isolation and reload. Rollback application images first; leaving the additive
review table in place preserves records. An old backend won't serve new review
routes, so roll frontend/backend back together. Do not downgrade production as an
incident shortcut: the new revision's downgrade drops review data. A schema rollback
requires backup, explicit approval and reviewed retention/data-loss implications.

## Required Phase 3 reconciliation before merging both

PR #3 remains unmodified and unmerged, at commit
`2613f92697929e818acf721bc44a7ca2b1b65a62`. No runner is enabled or security claim made.
Its `Submission` source table, trusted suite snapshots, `RunRequest`/`RunResult`
contracts, fenced retry worker and `/submissions` upload flow were inspected.
Reviews neither depend on nor alter those contracts. A task link is optional and
references the existing tasks table; review source digests are independent of
Phase 3's execution submission references. Do not substitute AI findings for runner
case results or alter the existing retry/lease/claim-token protections.

**Migration graph conflict:** both new revisions descend from `00391b88d2bb`:
Phase 4 `b5cbbc4049b7` adds only `code_reviews`; Phase 3 `3e039d93749d` adds submissions,
suite columns and case results. Their SQL additions do not overlap, but combining
the files as-is creates two heads. Phase 5A deliberately refuses multiple heads.
Before merging the second feature, reconcile the graph in a separately reviewed
change: if the second feature’s revision has never been applied to a database that must
be preserved, rebase that unmerged revision onto the first merged head; otherwise,
add an Alembic merge revision with both parents. Never rewrite
an applied migration or stamp away the discrepancy. Test existing-main upgrades,
both valid branch histories, repeat startup and model compatibility on disposable
PostgreSQL. This PR intentionally does not import Phase 3's migration.

**Source conflicts:** review `app/models.py`, `app/main.py`, `app/config.py`, frontend
challenge/workspace/proxy code, CI, Compose and README during the eventual merge.
Keep both models/routes and additive settings, retain Phase 5A's readiness/startup
logic, and keep review consent/history separate from Phase 3 submission/evaluation
UI. Re-run all suites after resolving. Phase 3 must still wait for its separately
required live gVisor deployment validation before merge/activation; Phase 4 mock
validation provides no sandbox assurance.
