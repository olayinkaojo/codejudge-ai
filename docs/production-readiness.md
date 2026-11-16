# Phase 6: audit, readiness and release checklist

This work starts from main `6616f1a` (Phase 4 merged). It polishes the existing
FastAPI/PostgreSQL/Next.js application; it does not replace features. There are no
new packages, paid services, schema revisions, data resets or production changes.
Readiness here means tested local behavior and a reviewable release candidate,
not a claim that production infrastructure or the Phase 3 sandbox was validated.

## Audit and changes

| Priority | Main-branch finding | Resolution |
| --- | --- | --- |
| High | A second POST after a timeout could create another task, evaluation or provider request. | Optional UUID `Idempotency-Key`, durable resource IDs and PostgreSQL advisory transaction locks deduplicate same-payload requests across replicas. Browser coalesces simultaneous submissions and retains the key after a failure. |
| High | Offline/timeout errors were raw fetch errors; cold starts gave generic failures. | Bounded 15-second browser requests around the existing 10-second BFF timeout, explicit recovery messages, no automatic mutation retries, and validated `Retry-After` propagation. |
| High | Expired sessions redirected silently. | Login explains missing/expired sessions; authentication inputs remain editable after failure and error announcements receive focus. |
| Medium | Evaluation history could make up to 100 requests in batches during an outage. | Pause after a batch encounters connection/authentication/service failure; retain entries with honest per-entry errors and explicit refresh. No result is fabricated. |
| Medium | Mobile navigation did not manage keyboard focus; small help text and some controls were hard to use. | Focus entry/trap/return and Escape close, inert background, current navigation state, stronger visible focus, clearer labels/contrast, 44px mobile controls and readable responsive review cards. |
| Medium | Login/registration lacked password visibility and specific uncertain-registration guidance. | Accessible visibility toggle, explicit label associations, duplicate submit guard, busy announcements, and advice to try signing in when registration may have completed. |

The dashboard keeps its sage palette, challenge cards and create flow. The editor
keeps self-hosted Monaco, draft download and the artifact-only execution boundary.
Review history/details keep provider disclosures, escaped snippets, source lines,
uncertainty, expiry and no-score behavior. Layouts are checked at desktop, tablet
and mobile widths. Monaco stays dynamically loaded; no remote fonts/editor assets,
analytics, paid performance services or additional runtime libraries are introduced.

## Duplicate submission contract

`POST /tasks`, `/evaluations` and `/reviews` accept an optional UUID header
`Idempotency-Key`. Existing clients can omit it and keep their original contract.
The key becomes that endpoint's resource UUID. PostgreSQL serializes the key with a
transaction-scoped advisory lock and a two-second lock wait. The existing ownership
checks apply: another owner gets 404, changed payload with an existing key gets 409,
and malformed keys get 422. A replay returns the resource's **current state**, using
the endpoint's existing 201/202 status; it does not rerun work or reserve review
usage again. It may return processing or a previously failed review. Inspect state,
then use the saved detail/history flow. No retry of failed provider work is implied.

The client key is held only in component memory, never cookies/localStorage or a
query string. A retry after an uncertain result uses the same key if the content is
unchanged. Editing content or explicitly submitting again after success creates a
new key. Reloads/navigation discard keys: check history before submitting again.
Review replay protection lasts while its record exists. Expired-but-still-stored
reviews reject replay; once retention physically deletes a record, its key is no
longer reserved. This is not indefinite deduplication or exactly-once billing.
A provider may have accepted a request before an interrupted review was marked
failed; failed/interrupted records are never automatically submitted again.

Deploy backend before frontend to activate cross-request replay protection. An old
backend ignores the optional header, so the frontend still works during a rollout
but cross-request deduplication is not available until the new API is running.
SQLite is only a unit-test convenience; distributed replay safety requires the
supported PostgreSQL deployment. No database migration is needed.

## Authentication and sensitive-data review

- Existing scrypt hashing, normalized usernames, expiring/revocable opaque bearer
  tokens and owner-only task/evaluation/review access remain in place.
- The bearer token stays in the server-managed encrypted HttpOnly cookie; production
  uses Secure, SameSite=Strict, host-only `__Host-codejudge`, path `/`. Backend token
  expiry and cookie payload expiry remain authoritative even though the cookie TTL
  is longer. Login rejects malformed token/expiry responses before saving a cookie.
- The BFF keeps exact mutation-origin checks, explicit method/path allowlists,
  server-controlled backend origin, redirects disabled, no-store responses and
  bounded JSON bodies. Only the validated replay header and bounded Retry-After are
  added; user-supplied URLs/credentials/forwarded authorization are not accepted.
- Source and provider errors are not logged; reviews store a digest instead of raw
  source. Feedback may contain fragments and retains the existing 30-day logical
  access window with opportunistic deletion. See [the privacy guide](code-reviews.md).
- Review budgets remain PostgreSQL-backed, including failed reservations, with
  per-user minute/day and global/day limits. Replays do not bypass or consume them.
- Real AI remains disabled by default and in local/CI validation. No real provider
  request, API cost, runner activation or production environment edit is performed.

## Remaining risks and requirements

These checks do not prove production readiness on their own:

1. **Authentication abuse controls:** registration/login do not yet have durable
   per-IP throttling or an account-recovery flow. Scrypt consumes CPU; review budgets
   do not protect login. Before a broader public launch, review free-tier-compatible
   edge/app abuse controls and load expectations. Do not claim brute-force/DoS
   protection from replay keys. This release does not invent an unreliable
   process-local distributed limiter or add a schema purely for the polish work.
2. **Free-tier availability/data durability:** Render cold starts can exceed the BFF
   deadline. Manual retry is deliberate. Verify current provider DB lifecycle,
   storage, backup/export/restore capabilities and capacity; no paid upgrade or
   backup guarantee is assumed. Opportunistic review purge is not a deletion SLA.
3. **Production-only settings:** verify existing HTTPS origins, SESSION_PASSWORD
   quality, DB TLS, log retention and secret rotation process through the authorized
   operators. No live secret values were inspected or changed by this work.
4. **CSP:** the existing Next.js CSP still permits inline scripts/styles. Nonce-based
   hardening needs a separate tested framework/deployment change; this release does
   not claim strict script CSP or complete accessibility/security certification.
5. **Drafts and uncertain outcomes:** drafts/keys are intentionally memory-only.
   Download before navigation or reauthentication. Review history is durable; the
   evaluation ID index remains browser-local, so loss of its storage after a lost
   response may require an operator lookup. Do not blindly repeat a POST after reload.
6. **Phase 3:** draft PR #3 remains untouched, unmerged and disabled. Before any
   eventual merge, reconcile its migration head with Phase 4's merged revision and
   preserve Phase 5A readiness. Its gVisor deployment still requires separate live
   security validation; neither these tests nor a mock review validate isolation.
7. **External AI:** adapter tests use mocks only. Keep configuration disabled. Any
   future opt-in needs separate approval for privacy, model compatibility, pricing
   and provider/project spending limits. No third-party free tier is assumed.

## Local validation and CI

Use dedicated disposable PostgreSQL test databases ending `_test` and
`_migration_test`; never production. Do not run destructive fixture suites
concurrently against the same database. The Python suite checks schema compatibility,
repeat migrations and legacy-row preservation, authentication/ownership, replay
conflicts/concurrency, durable budgets, recovery and execution fail-closed behavior.

Local validation on 2026-11-16: 118 Python tests passed with 94.68% application
coverage, 41 frontend tests passed, and all 6 desktop/tablet/mobile Playwright
journeys passed. Lint, formatting, optimized build, type checks, dependency and
Compose checks passed. A separate local production-image Compose stack passed
mock-review/authentication/fail-closed evaluation smoke and API restart persistence.
The managed build used a temporary BuildKit CA mount, without disabling TLS or
adding that certificate to the production image. No production verification or
remote CI result is implied.

```sh
ruff check .
ruff format --check .
pytest -q --cov=app --cov-report=term-missing --cov-fail-under=85
cd frontend
npm run lint
npm run format:check
npm test
npm run build
npm run typecheck
# Start a mock-only local API/worker, then point browser tests to its loopback URL:
BACKEND_URL=http://127.0.0.1:8008 E2E_BASE_URL=http://localhost:3006 npm run test:e2e
```

Build and type checks run sequentially because Next.js regenerates route types.
Playwright refuses non-loopback frontend/backend URLs: it creates synthetic records
and must not accidentally run against production. The suite covers real local
registration/login/challenge/editor/review/history/logout flows, replay through the
BFF, cold-start recovery, password controls, expired-session disclosure and mobile/
tablet/desktop layouts. A 503 is deliberately injected for recovery tests; no
successful runner/provider execution is simulated in the application.
CI uses the same added tests and viewport project with its existing PostgreSQL and
mock-only settings. Remote GitHub Actions results must be checked after pushing;
local success is not a claim that remote CI or production verification ran.

## Production-readiness checklist (review before approved release)

- [ ] Review the feature branch/draft PR and inspect CI results; do not merge/deploy automatically.
- [ ] Resolve or explicitly accept the remaining risks above, especially authentication abuse and free-tier DB recovery.
- [ ] Confirm current PostgreSQL revision is `b5cbbc4049b7` and `/ready` is healthy; this phase adds no revision.
- [ ] Confirm production AI is disabled and Phase 3 runner configuration remains disabled; never enable either during this rollout.
- [ ] Have an authorized operator verify existing HTTPS/session/origin/DB TLS settings without sharing secret values in issues or logs.
- [ ] Confirm backup/export and restore procedure, rollback image refs, retention and log policies.
- [ ] Obtain explicit production deployment approval. Deploy reviewed backend first, then frontend using existing free-tier infrastructure.
- [ ] Verify liveness/readiness, registration/login, expired-session behavior and logout/token revocation.
- [ ] Verify a mock review, owner isolation, same-key replay, 429 guidance and saved history reload; never expect an execution score.
- [ ] Check keyboard navigation, focus/error announcements and overflow on desktop/tablet/mobile; perform a manual assistive-technology review.
- [ ] Observe cold-start latency and failed requests without logging credentials/source or automatically repeating POSTs.
- [ ] Roll back application images together if needed. No schema rollback/data reset is necessary; old versions ignore the optional header.

No production release is authorized merely by checking local tests. Stop for review
and approval after pushing the draft PR.
