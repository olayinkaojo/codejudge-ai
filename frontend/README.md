# CodeJudge AI frontend

A responsive Next.js App Router workspace using TypeScript, Tailwind CSS, and a
self-hosted Monaco Python editor. Requires Node.js 24 and the FastAPI backend from
`feature/production-backend` (or that branch merged into main).

## Run locally

From the repository root, start the backend with `docker compose up --build -d`.
The API must be available at `http://127.0.0.1:8000`. Then:

```sh
cd frontend
cp .env.example .env.local
npm ci
npm run dev
```

Open `http://localhost:3000`. Use **localhost**, matching `APP_ORIGIN`; accessing
through a different hostname requires updating that setting. In this cloud
workspace npm may need `npm --cache /tmp/codejudge-npm ci` because the default home
cache is not writable. The backend's cloud Docker CA guidance still applies.
Create an account and sign in. Accounts start with an empty dashboard; create your
own challenges. The UI has no seeded results, fake submissions, difficulty labels,
leaderboards, or fabricated success metrics.

## What works with the current API

| Frontend flow      | Actual FastAPI contract                                                                            |
| ------------------ | -------------------------------------------------------------------------------------------------- |
| Register           | `POST /auth/register` with username/password; then sign in separately                              |
| Sign in            | `POST /auth/token`; token stays inside the server-managed session cookie                           |
| Sign out           | `DELETE /auth/token`; only claims success when revocation succeeds or the token is already invalid |
| Dashboard          | `GET /tasks?limit=20&offset=N`; search applies to loaded challenges                                |
| Create challenge   | `POST /tasks` with title, description, max_score                                                   |
| Challenge          | `GET /tasks/{uuid}`                                                                                |
| Request evaluation | `POST /evaluations` with task_id and submission_reference; expects 202                             |
| Result / polling   | `GET /evaluations/{uuid}`; polling every 3 seconds only while queued/running                       |

`/api/auth` and `/api/backend/*` are **Next.js server routes**, not new FastAPI
endpoints. The proxy only allows the methods/routes above, forwards only known
pagination parameters, disables redirects/caching, bounds JSON request bodies to
128 KiB, and has a 10-second upstream timeout. FastAPI remains the authority for
validation, authentication, ownership, and scoring. Review routes and their backend implementation are documented below.

### Python editor and artifact boundary

Monaco and its Python grammar/worker are bundled locally; no editor code is loaded
from a CDN. A textarea mode supports assistive technology or editor fallback.
Source code exists only in page memory. Download `solution.py` before navigating
away; refresh/unload warns about edited drafts, but internal navigation does not
persist them. No code is executed in the browser, API, or frontend server.

The backend has **no source-upload endpoint**. Download your solution and use your
external runner's authorized artifact workflow to obtain an artifact ID. The UI
requires an explicit acknowledgment that evaluation references that artifact, not
the contents of the editor. It sends only task_id and the opaque artifact ID.
Without a configured external runner, the worker records a failed job with no
score. No working artifact upload or hostile-code sandbox is implied by this UI.

### History and results

The backend has **no evaluation-list endpoint**. History is therefore a bounded
(100 records), per-username browser-local index of evaluation IDs, task titles and
request times created through this UI. It stores neither tokens nor source code;
each displayed job state is fetched from the authenticated backend, with at most
five concurrent refresh requests. History survives reloads but not sign-out,
cleared storage, or switching devices. A known evaluation UUID can be opened
manually; ownership is still checked by FastAPI. Private browsing/storage failures
can prevent history indexing; retain the result URL in that case.

Queued and running jobs show no score. Failed jobs explain the backend error
without pretending tests passed. Successful results render only actual backend
counts, score, and feedback. Feedback is escaped as text, never injected as HTML.
The API provides no per-test output, execution duration or code snapshot, so the
interface does not invent those fields. A polling failure stops automatic polling
and offers retry; it never silently changes a result to successful.

## Session security and deployment

Server-only environment variables (never use a `NEXT_PUBLIC_` prefix):

- `BACKEND_URL`: FastAPI origin, default `http://127.0.0.1:8000`. Use HTTPS across
  untrusted networks. Credentials, paths, query strings, and fragments are rejected.
- `APP_ORIGIN`: canonical browser origin, e.g. `https://judge.example.com`.
  Required in production. Mutation requests require an exact matching Origin and
  reject cross-site Fetch Metadata. Do not loosen this check to fix hostname mismatches.
- `SESSION_PASSWORD`: at least 32 random characters from a secret manager,
  required in production. All Next.js instances need the same key. Never commit it.

The session is authenticated and encrypted by iron-session. Production cookies
use the `__Host-codejudge` name, Secure, HttpOnly, SameSite=Strict, Path=/, and no
Domain attribute. Browser JavaScript never receives the FastAPI bearer token;
there is no token in localStorage, sessionStorage, URLs, or client props. The
session's backend expiry is checked before forwarding; backend 401 responses clear
the cookie and protected navigation returns to login. Cookies have a maximum
30-day envelope lifetime, but cannot extend the actual backend token expiry.
Development uses an HttpOnly cookie over local HTTP and an ephemeral key if no
key is supplied; restarting the dev server can invalidate those sessions.

```sh
npm ci
npm run build
# Inject SESSION_PASSWORD, APP_ORIGIN and BACKEND_URL securely, then:
npm start
```

Use HTTPS termination in production. Configure trusted routing and shared edge
rate limits for authentication, account creation and evaluation submission;
backend rate-limiting, isolated runner provisioning, artifact storage, database
operations, monitoring, and retention remain infrastructure responsibilities.
The production CSP disallows external scripts/connections, frames and framing,
but permits inline styles/scripts for Next hydration and Monaco. A stricter
nonce-based CSP is a future hardening step; HTTPS/HttpOnly cookies do not replace
XSS prevention. No arbitrary upstream proxy destinations are exposed to clients.

## Checks

```sh
npm run lint
npm run format:check
npm test
npm run build
npm run typecheck
# Backend, migrated PostgreSQL, and a worker with SANDBOX_URL unset must be running:
npx playwright install --with-deps chromium
npm run test:e2e
```

Run build/typecheck sequentially because Next regenerates its route types during
build. Playwright starts the dev frontend with a matching APP_ORIGIN. In this cloud
machine, the installed Chromium can be used with
`PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/chromium npm run test:e2e`.

Unit/component tests cover encrypted cookies, CSRF/origin policy, proxy allowlists,
body limits, login/register/logout behavior, history isolation/storage failure,
realistic evaluation states, escaped feedback, and network errors. Desktop and
mobile browser tests use the **real backend**: register/login, verify HttpOnly
cookies and token-free responses/storage, create a challenge, load Monaco, edit and
download Python, submit only an artifact reference, observe honest runner failure,
reload history, reject cross-origin mutations, and sign out. Tests create synthetic
accounts/tasks and do not run submissions. Screenshots/traces stay in ignored test
output directories. CI boots its own PostgreSQL/API/worker stack.

## Code reviews

The challenge editor includes **Review code**, which sends the current draft only
on explicit action. Default feedback is labeled **Simulated · mock**. The optional
external provider requires server opt-in and an explicit consent checkbox; the UI
shows its disclosure before any source transmission. The API key stays in FastAPI.

`POST /reviews`, `GET /reviews/config`, `GET /reviews/{uuid}`, and paginated
`GET /reviews?limit=20&offset=N` are forwarded by the authenticated BFF. `/reviews`
and `/reviews/{uuid}` use durable, owner-only backend history, not local storage.
Source and provider output are rendered as escaped text; snippets are never run.
Processing/failure states do not produce execution scores. Completed reviews apply
to the submitted snapshot; later editor changes need a new explicit request.

The existing 10-second proxy timeout can expire on a Render cold start. Do not
retry review POST automatically: it may already have reserved usage or incurred
external cost. Check review history first. History GET recovers interrupted review
states after 20 seconds; it never retries provider work. The draft remains in
memory until navigation/reload. Download it before leaving.

See [the backend guide](../docs/code-reviews.md) for limits, environment variables,
retention, local testing, and safe deployment. The browser workflow covers editor
review, persisted results across reload, and desktop/mobile layouts alongside the
existing registration, authentication, challenge, and fail-closed evaluation flow.

## Phase 6 reliability and accessibility

The workspace now explains cold starts and expired sessions, bounds browser
requests, preserves validated rate-limit guidance and never automatically retries
a mutation. Challenge/evaluation/review forms coalesce in-flight submissions and
reuse an in-memory replay key after uncertain failure; check history before
retrying, especially after navigation/reload. Authentication has explicit labels,
a password visibility control, focused error announcements and duplicate-submit
protection. Mobile navigation traps/restores focus, closes with Escape and makes
the background inert. Help-text contrast, focus rings, touch targets and review
layouts retain the existing sage identity.

Playwright now covers desktop/tablet/mobile and supports a separate local frontend
port via `E2E_BASE_URL=http://localhost:3006`. Both frontend and configured backend
URLs must be loopback HTTP addresses because these tests create records. For
managed cloud Chromium, set `PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/chromium` if needed.
See [the audit/checklist](../docs/production-readiness.md) for production limitations
and release/rollback requirements. No production environment changes are needed
for these UI improvements.

## Authentication hardening (Phase 6B)

Registration now reports a generic processed request for new/existing usernames,
without an existence-specific status or returned account ID. Existing passwords
are never replaced; sign in with the original password for an existing account.
The BFF keeps its session/origin boundaries and passes bounded numeric auth
Retry-After guidance to the UI. It does not forward arbitrary browser IP headers.
See [authentication admission policy](../docs/authentication-security.md) for the
shared-network tradeoffs and reviewed proxy configuration requirements.
