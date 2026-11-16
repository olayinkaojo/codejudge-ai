# Durable authentication admission controls (Phase 6B)

Login and registration now reserve admission in PostgreSQL **before scrypt and
account lookup** for syntactically valid credentials. Existing passwords, tokens,
revocation and ownership checks are unchanged. Request-body limits and validation
still reject invalid inputs cheaply; syntactically invalid requests do not enter
these counters and never perform password hashing.

## Policy and durability

| Scope | Default | Window |
| --- | --- | --- |
| All login + registration attempts, all replicas | 20 | UTC minute |
| Registration attempts, all replicas | 10 | UTC minute |
| Login attempts per source network | 100 | UTC 5 minutes |
| Registration attempts per source network | 60 | UTC hour |
| Login attempts per network + normalized username | 6 | UTC 5 minutes |

Global counters include syntactically valid attempts, including successes, incorrect
credentials, duplicate registrations and attempts whose HTTP response was lost.
Fixed global gates run first; denied traffic cannot allocate unlimited new
identity rows. Inner source/pair counters are reserved only after passing the
preceding gates. Atomic PostgreSQL UPSERTs
reserve counters in one transaction across API replicas; PostgreSQL time defines
window boundaries. A two-second lock wait and normal DB timeouts prevent indefinite
waiting. Admission failure is fail-closed (safe 503), never unlimited password work.
Rejected attempts increment saturated counters without integer growth. A 429 has
the same generic body and a positive Retry-After in seconds until the first
blocking gate resets; another budget may still apply on the next explicit attempt. BFF auth responses preserve only bounded numeric guidance;
the frontend announces it and does not automatically retry.

Limits are **fixed windows**, permitting bursts at a boundary; they are not a
sliding-window or concurrency/memory isolation guarantee. Caps intentionally bound
shared free-tier password work and may reject legitimate traffic during an attack.
Monitor coarse events/load and review settings before separately approved tuning:
`AUTH_GLOBAL_PER_MINUTE` (2–1000), `AUTH_REGISTER_PER_MINUTE` (1–100),
`AUTH_NETWORK_LOGINS` (5–1000), `AUTH_NETWORK_REGISTRATIONS` (2–1000), and
`AUTH_PAIR_LOGINS` (2–100). Keep settings consistent across all API instances.
No production variable is changed by this branch.

There is no account-wide permanent lock or failure flag on User. Different usernames
on a shared NAT have independent pair budgets, while the higher shared network and
global caps protect overall capacity. A known username and an unknown username use
the same admission policy and scrypt-cost verification path. An attacker sharing a
network can still temporarily exhaust that network/pair's fixed window; distributed
sources can reach global caps. This mitigates brute-force/registration abuse but
is not complete botnet, credential-stuffing or denial-of-service protection.
Existing authenticated tasks/reviews and token revocation are not blocked by auth
admission caps. No account-recovery/MFA service is introduced or claimed.

## Proxy and address boundary

The supported API startup uses **`--no-proxy-headers`** so Uvicorn does not silently
replace the socket peer before the application's trust check. Keep that flag for
native commands, CI and custom Render startup too. Do not combine this logic with
an unreviewed framework-wide trust-all setting.

Default `AUTH_TRUSTED_PROXY_CIDRS` is empty: Forwarded/X-Forwarded-For/X-Real-IP
cannot select a bucket. Only X-Forwarded-For is optionally supported, when the
actual immediate peer belongs to an explicitly configured comma-separated CIDR
allowlist. The chain is parsed right-to-left, removing only known trusted hops and
stopping at the first untrusted address. Client-supplied leftmost entries cannot
skip an untrusted hop. Malformed, over-512-byte or over-eight-hop chains fall back
to the actual peer. Trust-all IPv4/IPv6 CIDRs are rejected. IPv4-mapped IPv6 addresses
normalize to IPv4; other IPv6 addresses share /64 budgets to limit trivial rotation.
Unparseable peers use one conservative shared bucket, never a guessed header value.

Before any future trust configuration, an operator must verify actual ingress peer
ranges, header rewriting/stripping and reachability on the deployed platform.
No Render/Vercel CIDRs or origin guarantees are invented here. Public or shared
networks should not be allowlisted merely because the app sees their addresses.
The Next.js BFF intentionally does **not** relay arbitrary browser IP headers.
Consequently, users can share the BFF's egress/network budget; this is an honest
free-tier fairness tradeoff. The per-network registration cap is relatively high,
username pairs are independent, and caps are configurable. Reliable original-user
IP identity through multiple providers would require separately reviewed verified
platform metadata/forwarding, not blindly copying a browser header.

## Privacy, enumeration and logs

`auth_rate_secrets` stores one randomly generated privacy key, initialized atomically
on first admission. `auth_rate_buckets` stores only HMAC-SHA256 scope identities,
hits and reset times, never passwords, raw usernames, raw IPs, request bodies,
raw tokens or user-agent strings. The DB protects the privacy key like other
sensitive application state. HMAC is pseudonymization, not anonymization against
someone who compromises the database/key. Scope keys reuse bounded state; up to
100 counters more than a day past reset are purged per admission. Physical cleanup
is opportunistic, not a deletion deadline, and backups retain historical state.
The privacy key must not be deleted/rotated casually: doing so resets effective
admission histories. No secret/key value is logged or added to a migration file.

Security log events are allowlisted categories: admission, rate limit (action/scope),
credential rejection, successful login, and generic registration processing.
They contain no identity, password, token, DB URL or response body. DB failures use
the existing safe categorizer. Never enable HTTP body/debug capture for auth or
backup processes. A rate limiter is not a substitute for log/host access controls.

**Intentional response-contract change:** `POST /auth/register` returns 201 with
`{"detail":"Registration request processed. Continue to sign in."}` for both new
and existing usernames. It no longer exposes an account ID or 409 existence oracle.
An existing username's password is never replaced. The frontend qualifies the
registration result and directs an existing user to their original password.
Registration is not a fictitious login; tokens are issued only by successful
`POST /auth/token`. Invalid credentials remain generic 401. This reduces obvious
enumeration; it does not claim elimination of every network/database timing channel.
External API clients relying on the former registration ID/409 must adopt the generic
contract. The existing Next.js BFF/session workflow remains compatible.

## Migration, verification and rollback

Revision `f6b20261116` descends from main's `b5cbbc4049b7`, adding only the two auth
admission tables/index/check constraint. Existing applied migrations are unchanged.
No backfill or replacement of User/Token data occurs. SQLite support is exclusively
for unit tests; production Settings require PostgreSQL. Tests exercise parallel
sessions, known/unknown names, shared sources, spoofed/invalid chains, reset/cleanup,
DB failure before scrypt, registration privacy and restored existing authentication.

This branch does not run a production migration or deployment. Before a separately
approved release, obtain a verified external backup/restore drill, review defaults,
apply the additive migration with the existing coordinated procedure, then release
matching API/frontend versions. `/ready` fails closed on old/missing schema.

Because readiness checks the exact migration head, an old API image will not be
ready against the newer revision merely because the tables are additive. Prefer
a reviewed roll-forward correction. A rollback needs a separately approved plan:
either a rollback build with compatible migration/readiness metadata, or reviewed
downgrade to `b5cbbc4049b7` paired with the old application. That downgrade drops
only new rate state, loses admission history and removes the new protection; it
must not reset existing user tables or be performed automatically. Preserve a
backup and assess exposure before doing so. No live rollback is performed here.

Phase 3 remains unmerged and disabled. Its old independent migration head still
requires a reviewed graph reconciliation before any eventual merge, plus separate
live isolation validation. This feature does not change its worker/runner contract,
mock AI defaults, provider configuration or execution security assumptions.
