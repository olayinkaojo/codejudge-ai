# CodeJudge AI frontend

A responsive Next.js App Router workspace using TypeScript, Tailwind CSS, and a
self-hosted Monaco Python editor. Requires Node.js 24 and the FastAPI backend from
`main` including Phase 3 migrations.

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
cache is not writable. Keep TLS verification enabled when configuring cloud package-download trust.
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
| Create challenge   | `POST /tasks` with title, description, max_score, test_suite_id                                    |
| Challenge          | `GET /tasks/{uuid}`                                                                                |
| Test catalog       | `GET /test-suites`; challenge creation binds a versioned suite                                     |
| Source snapshot    | `POST /submissions` with task_id and source; returns an immutable reference                        |
| Request evaluation | `POST /evaluations` with task_id and that submission reference; expects 202                        |
| Result / polling   | `GET /evaluations/{uuid}`; polling every 3 seconds only while queued/running                       |

`/api/auth` and `/api/backend/*` are **Next.js server routes**, not new FastAPI
endpoints. The proxy only allows the methods/routes above, forwards only known
pagination parameters, disables redirects/caching, bounds JSON request bodies to
128 KiB, and has a 10-second upstream timeout. FastAPI remains the authority for
validation, authentication, ownership, and scoring. Phase 3 adds the documented catalog/submission contracts to FastAPI.

### Python editor and execution boundary

Monaco and its Python grammar/worker are bundled locally; no editor code is loaded
from a CDN. A textarea mode supports assistive technology or editor fallback.
Unsubmitted draft code stays only in page memory. Download `solution.py` before navigating
away; refresh/unload warns about edited drafts, but internal navigation does not
persist them. No code is executed in the browser, API, or frontend server.

Phase 3 adds `POST /submissions`. On explicit consent and Request evaluation,
the UI stores an immutable snapshot of the editor, then queues that reference.
If queueing fails, an unchanged retry reuses the successfully created snapshot;
changes to the code create a new one. Source is not stored in localStorage or
history and is never executed by Next.js. Limit: 16,000 characters / 32 KiB UTF-8.
The snapshot is stored as data in PostgreSQL for the dedicated worker to deliver
to the authenticated isolated runner. It is not echoed by the submission API.

Choose a catalog suite when creating a challenge. Its standard-input/output
contract is inserted into the description; editing the description does not
change the tests. Old challenges with no suite disable evaluation and explain why.
Without a configured and validated gVisor runner, the worker fails closed with no
score. See [runner security/deployment](../runner/README.md). There is no native or
ordinary-Docker fallback and no browser-side Python execution.

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
Phase 3 case results show stable case labels, passed/failed status, generic
reasons, and measured lifecycle durations (including sandbox startup). Expected
answers and raw stdout/stderr remain hidden; a submitted-code download endpoint
is not provided. Legacy completed results can have no structured case details. A polling failure stops automatic polling
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
accounts/tasks and, on this local stack without a validated runner, do not run
submissions. Live gVisor execution tests run only on a separately qualified host. Screenshots/traces stay in ignored test
output directories. CI boots its own PostgreSQL/API/worker stack.
