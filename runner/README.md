# Isolated Python execution service — Phase 3

This is a dedicated control plane for **gVisor/runsc**, not an ordinary Docker
execution worker. The API and application worker store/transport data; only the
separately deployed guest interpreter executes submission source. There is no
runc/native/subprocess fallback. Docker is used solely to manage OCI sandboxes
with `runtime=runsc`.

**Validation status in this cloud task:** the guest image builds, protocol/security
unit tests pass, and the actual host admission check rejects rootless Docker with
unapproved `--ignore-cgroups` configuration. Untrusted submissions were **not run**
here. Full live gVisor enforcement tests are intentionally gated and unrun on this
host. This repository is not evidence of production-grade sandbox security.

## Threat model and assumptions

Untrusted students control Python source, standard output/error, return codes,
signals, and attempts to use sockets/files/processes. They do not control the
runner host, runsc binary/configuration, immutable guest image, challenge catalog,
application database, worker service credential, or TLS termination. The native
controller, independent watchdog, Linux kernel, Docker daemon, runsc/Sentry/Gofer,
image supply chain, and operators are trusted. gVisor reduces host-kernel exposure
through its userspace kernel; it does not establish safety against every unknown
runtime, host, hardware, or side-channel vulnerability.

Use a **dedicated disposable Linux VM/host**, separate from API/database machines,
with no application credentials, cloud identity, sensitive mounts, or production
workloads. Docker socket access is effectively root-equivalent on that dedicated
host. Never mount it into the API/worker, nor run this controller beside app
secrets. Host firewall rules must deny metadata/internal service access and
unnecessary egress even if the sandbox boundary is compromised. Authenticate and
rate-limit the private control endpoint through HTTPS (prefer mTLS as well).

Official references:

- [gVisor architecture](https://gvisor.dev/docs/architecture_guide/intro/)
- [Security model](https://gvisor.dev/docs/architecture_guide/security/)
- [runsc installation and checksums](https://gvisor.dev/docs/user_guide/install/)
- [Docker integration](https://gvisor.dev/docs/user_guide/quick_start/docker/)

Install a current, patched release from the official verified distribution and
record its checksum/version. Do not treat a runtime name alone as proof of
isolation. Review the host/kernel/runtime security posture and run the admission
suite on **each actual deployment**. Rootless Docker, ignored cgroups, remote
Docker sockets, unknown runsc flags, and runtime fallbacks are unsupported.

## Enforced policy per fresh test sandbox

| Resource / boundary | Policy |
| --- | --- |
| Runtime | Explicit runsc; only default flags or `--platform=systrap` / `--platform=kvm` |
| Host prerequisites | Rootful Docker, cgroup v2, seccomp, same-host native controller |
| Guest identity | UID/GID 65532, all capabilities dropped, no-new-privileges |
| Network | Docker network `none`; no host/shared networking, guest network probes |
| Filesystem | Read-only minimal guest image; no host bind mounts, volumes, devices or sockets |
| Writable data | Regular writable storage: `/tmp` tmpfs, 8 MiB, noexec/nosuid/nodev; IPC mode none (no /dev/shm) |
| Environment | Explicit harmless environment; bootstrap clears everything except PATH/LANG before source execution |
| CPU | One CPU quota in an actual dedicated cgroup; RLIMIT_CPU 1s soft / 2s hard |
| Memory | Actual 512 MiB host cgroup including Sentry, swap disabled; Python RLIMIT_AS 128 MiB |
| Processes | Host pids.max 128 (runtime threads), guest RLIMIT_NPROC 1 (no child processes/threads) |
| Wall time | Controller deadline 5s; independent watchdog reaps at 6s, with polling/removal latency |
| Output | 32 KiB combined stdout/stderr; bounded multiplexed socket reads; daemon logs disabled |
| Other limits | 32 file descriptors, 32 KiB per regular file, no core dumps |

The daemon's configured limits are not accepted on faith: the controller inspects
the started container and reads its **actual host cgroup files** before releasing
any source. The trusted bootstrap waits for one bounded JSON line. Guest source
never appears in container command arguments, mounted host files, logs, or test
verdict files. Each test starts a fresh sandbox; no shared execution state exists.
The source itself is written only to the guest tmpfs, then exec'd by the trusted
guest bootstrap with inherited hard limits and a minimal environment.

The watchdog is a separate process/service with restart supervision. A fresh
heartbeat is required before work is admitted. The controller enforces its own
wall deadline; the watchdog independently kills/removes expired owned containers,
including orphans after controller crashes. If cleanup fails, the controller
quarantines itself. Unknown/malformed resource configuration, orphan containers,
missing watchdog health, and infrastructure errors yield 503 with **no results**.
Host scheduling/daemon failure can delay removal: this is not a hard real-time
system. Both services and Docker must be supervised; node fencing/reboot and
alerting are required if the host or both supervisors fail. Resource limits and
signed admission evidence do not protect a compromised host administrator.

## Admission evidence

Before accepting submissions, `python -m runner.validate` runs trusted adversarial
fixtures **inside gVisor only after the base checks pass**. It checks correctness,
forged verdict output, clean environment, host filesystem denial, external and
metadata/internal networking denial, child-process denial, memory allocation
limits, CPU termination, wall termination, and stdout/stderr floods.

Only a fully passing run issues a short-lived HMAC-signed `admission.json`, bound
to the guest image ID, host boot ID, exact runsc binary SHA-256, runtime flags and
protocol. Evidence expires after one hour; changing the image/binary/boot, missing
checks, invalid signatures, or failed renewal closes admission. Operator-controlled
state files are private (0700 directory / 0600 journal/evidence). No public
endpoint can create or modify admission evidence.

Renew admission during controlled maintenance before expiry. Do not revalidate
on a busy node: stop/quiesce the controller, let the watchdog clean any orphaned
jobs, validate, then restart. Requests interrupted by maintenance remain subject
to the application's durable retry policy. Never manually write evidence or turn
off a failed check to admit work. The controller systemd unit runs validation as
an ExecStartPre prerequisite. Admission expiry is intentionally fail closed; it
is not silently extended by serving traffic.

## Provisioning on a suitable isolated host

1. Provision patched Linux + rootful Docker + cgroup v2 + verified runsc using the
   official installation guidance. Register runsc by **absolute binary path**.
   Do not use `--ignore-cgroups`, host networking, disabled seccomp, or privileged
   guests. Confirm the host has sufficient memory/CPU for Sentry overhead.
2. Install reviewed `runner/`, `contracts/`, `constraints.txt` and dependencies at
   `/opt/codejudge`; do not deploy application `.env` files or database bindings.
   Create an unprivileged `codejudge-runner` user with dedicated daemon access.
3. Build the minimal guest from its restricted context:

   ```sh
   docker build -t codejudge-python:reviewed runner/guest
   docker image inspect codejudge-python:reviewed --format '{{.Id}}'
   ```

   Audit/scan the base and resulting image. Set `RUNNER_IMAGE` to the resulting
   **sha256 image ID**, never a mutable tag. The controller does not pull images.
   Rebuild for Python/base security updates and revalidate the new image.
4. Install a virtualenv and `pip install -r runner/requirements.txt`. Provision
   `/etc/codejudge-runner.env` via a secret manager with permissions 0600:

   ```text
   RUNNER_TOKEN=<at least 32 random characters; never commit>
   RUNNER_IMAGE=sha256:<audited image ID>
   RUNNER_STATE_DIR=/var/lib/codejudge-runner
   RUNNER_DOCKER_SOCKET=unix:///var/run/docker.sock
   ```

5. Review/install the sample units in `deploy/`. Start the watchdog first. Start
   the controller; its pre-start validation must actually pass. Serve the private
   loopback port 9000 through authenticated HTTPS infrastructure. Use one controller
   process per host (an exclusive file lock prohibits extra workers).
6. Configure **only the application worker** with `SANDBOX_URL=https://runner-host/evaluate`,
   `SANDBOX_TOKEN` matching the runner, `SANDBOX_TIMEOUT=75`, `LEASE_SECONDS=180`.
   The runner receives neither the database URL nor browser/session credentials.
7. Verify authenticated `/ready`, run `RUNNER_LIVE_TESTS=1 pytest -q
   tests/security/test_gvisor_live.py` on the dedicated validation host, and retain
   deployment-specific evidence. Do not enable Internet-facing traffic based on
   unit-test success. Monitor errors, admission expiry, oldest queue age, watchdog
   heartbeat, resource saturation, cleanup, and host/runtime patch levels.

The controller is intentionally **not part of application Docker Compose**. The
local Compose stack without a runner still records honest failure, and can be
used for API/frontend development without ever executing submissions.

## Protocol, grading, and durable delivery

The worker sends authenticated POST `/evaluate`, an Idempotency-Key equal to the
evaluation UUID, and the `python-stdio-v1` RunRequest in
`contracts/evaluation.py`: IDs, immutable source, and the task's snapshotted suite.
Suites have up to 8 cases. Each case supplies only stdin to the guest. The
controller compares stdout to the expected UTF-8 bytes **outside** the sandbox
(CRLF normalized to LF, other whitespace exact). It ignores guest-produced JSON
as a verdict. Nonzero exit, timeout, output/resource limit or wrong output fails
that case. Infrastructure/isolation failures abort the whole attempt without
committing partial results. Expected values and raw program output are never
returned to students.

Case results include stable ID/label, passed/failed, generic reason, and measured
wall milliseconds including sandbox lifecycle overhead. MemoryError can be a
normal Python runtime failure rather than a host OOM; not every nonzero exit can
be attributed to a specific resource. Do not infer an algorithm's CPU benchmark
from these lifecycle durations.

A 55-second request budget bounds a whole suite; budget exhaustion is an
infrastructure failure, not a fabricated case verdict. The service serializes
execution (429 when busy). Its private SQLite journal
persists completed results and an immutable request hash by evaluation UUID.
Retries return the same committed result; reusing an ID for changed source/tests
returns 409. After a crash before commit, execution can repeat in a fresh sandbox;
there is no claim of exactly-once computation. The watchdog removes old guests,
and orphan detection prevents admitting new work until cleanup. Back up/retain
runner journals per policy. For scaling, assign jobs to stable runner shards or
share a properly designed idempotency store; a generic load balancer with separate
journals does not provide cross-host result deduplication.

PostgreSQL still owns the application queue. Leases, SKIP LOCKED, attempt limits
and claim-token fencing are preserved. Retryable 429/5xx and transport failures
use delayed requeue (20s, 40s, then at most 60s for larger configured attempt
limits). Invalid results or mismatched case identities are rejected. Old opaque
artifact jobs cannot be executed by the new worker and fail closed.

## Test interpretation

- Ordinary CI runs API/queue/runner-protocol/security unit tests and builds both
  images. Its runner engine double **never executes Python**. Tests of invalid
  Docker flags, ignored cgroups, mounts/secrets, watchdog failure, cleanup and
  admission evidence are policy/contract tests, not a sandbox certification.
- `.github/workflows/sandbox-deployment.yml` is manual, main-only, requires a
  protected environment and an operator-provisioned ephemeral self-hosted
  `codejudge-gvisor` host. It never runs pull-request-controlled code automatically
  on a privileged self-hosted runner. Configure required reviewers and main-only
  deployment rules on the GitHub environment before enabling it; the environment
  name alone does not install those protections. Do not share production credentials with CI.
- `tests/security/test_gvisor_live.py` is skipped unless explicitly enabled and
  then fails if any deployment prerequisite or adversarial probe fails. An absent
  host is a deployment blocker, not a reason to mark this check as passed.
