"""Durable PostgreSQL queue consumer. Never imports or executes submission code."""

import argparse
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import httpx
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db import session_factory
from app.models import Evaluation, Submission, Task, now
from app.schemas import SandboxResult
from contracts.evaluation import RunRequest, Suite

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    id: UUID
    claim_token: str
    task_id: UUID
    reference: str
    max_score: int
    attempt: int
    request: RunRequest


def claim(factory: sessionmaker, settings: Settings) -> Job | None:
    timestamp = now()
    eligible = or_(
        and_(Evaluation.status == "queued", Evaluation.available_at <= timestamp),
        and_(
            Evaluation.status == "running",
            Evaluation.lease_until < timestamp,
        ),
    )
    with factory.begin() as db:
        # Lock only one row at a time. PostgreSQL SKIP LOCKED allows independent workers.
        while True:
            row = db.scalar(
                select(Evaluation)
                .where(eligible)
                .order_by(
                    Evaluation.created_at,
                    Evaluation.id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            if row.attempts >= settings.max_attempts:
                row.status, row.error = "failed", "retry_limit_exceeded"
                row.completed_at, row.lease_until, row.claim_token = timestamp, None, None
                db.flush()
                continue
            row.status = "running"
            row.attempts += 1
            row.claim_token = secrets.token_hex(24)
            row.lease_until = timestamp + timedelta(seconds=settings.lease_seconds)
            row.error = None
            task = db.get(Task, row.task_id)
            try:
                submission = db.get(Submission, UUID(row.submission_reference))
                if (
                    submission is None
                    or submission.task_id != row.task_id
                    or submission.owner_id != row.owner_id
                ):
                    raise ValueError("invalid submission")
                request = RunRequest(
                    evaluation_id=row.id,
                    task_id=row.task_id,
                    submission_reference=submission.id,
                    source=submission.source,
                    suite=Suite.model_validate(task.suite_spec),
                )
            except (ValueError, TypeError):
                row.status, row.error = "failed", "invalid_submission_or_suite"
                row.completed_at, row.lease_until, row.claim_token = timestamp, None, None
                db.flush()
                continue
            return Job(
                row.id,
                row.claim_token,
                row.task_id,
                row.submission_reference,
                task.max_score,
                row.attempts,
                request,
            )


def finish(factory, job, *, result=None, error=None, retry=False):
    values = {"claim_token": None, "lease_until": None}
    if result is not None:
        score = Decimal(job.max_score) * Decimal(result.tests_passed) / Decimal(result.tests_total)
        values.update(
            status="succeeded",
            tests_passed=result.tests_passed,
            tests_total=result.tests_total,
            score=score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            feedback=result.feedback,
            case_results=[case.model_dump() for case in result.case_results],
            error=None,
            completed_at=now(),
        )
    else:
        if retry:
            values["available_at"] = now() + timedelta(seconds=min(60, 10 * 2**job.attempt))
        values.update(
            status="queued" if retry else "failed", error=error, completed_at=None if retry else now()
        )
    with factory.begin() as db:
        # Fencing prevents an expired worker from overwriting a newer attempt.
        updated = db.execute(
            update(Evaluation)
            .where(
                Evaluation.id == job.id,
                Evaluation.status == "running",
                Evaluation.claim_token == job.claim_token,
                Evaluation.lease_until > now(),
            )
            .values(**values)
        )
        return updated.rowcount == 1


class InvalidResult(Exception):
    pass


def request_result(client, settings, job):
    headers = {"Idempotency-Key": str(job.id), "Accept-Encoding": "identity"}
    deadline = time.monotonic() + settings.sandbox_timeout
    if settings.sandbox_token:
        headers["Authorization"] = "Bearer " + settings.sandbox_token.get_secret_value()
    # Endpoint is operator-controlled. Artifact references never become URLs or commands.
    with client.stream(
        "POST",
        settings.sandbox_url,
        headers=headers,
        json=job.request.model_dump(mode="json"),
    ) as response:
        response.raise_for_status()
        if response.headers.get("Content-Encoding", "identity") != "identity":
            raise InvalidResult("compressed_result_not_supported")
        data = bytearray()
        for chunk in response.iter_bytes(chunk_size=4096):
            if time.monotonic() > deadline:
                raise httpx.ReadTimeout("sandbox deadline exceeded")
            data.extend(chunk)
            if len(data) > 65536:
                raise InvalidResult("response_too_large")
        result = SandboxResult.model_validate_json(bytes(data))
        expected = [(case.id, case.label) for case in job.request.suite.cases]
        if [(case.id, case.label) for case in result.case_results] != expected:
            raise InvalidResult("suite_result_mismatch")
        return result


def run_once(factory=None, settings=None, client=None):
    factory = factory or session_factory()
    settings = settings or get_settings()
    job = claim(factory, settings)
    if job is None:
        return False
    if not settings.sandbox_url:
        finish(factory, job, error="sandbox_not_configured")
        return True
    owned_client = client is None
    client = client or httpx.Client(timeout=settings.sandbox_timeout, follow_redirects=False, trust_env=False)
    try:
        result = request_result(client, settings, job)
    except httpx.HTTPStatusError as exc:
        transient = exc.response.status_code >= 500 or exc.response.status_code == 429
        finish(
            factory, job, error="sandbox_http_error", retry=transient and job.attempt < settings.max_attempts
        )
    except httpx.TransportError:
        finish(factory, job, error="sandbox_unavailable", retry=job.attempt < settings.max_attempts)
    except (InvalidResult, ValueError):
        finish(factory, job, error="invalid_sandbox_result")
    else:
        finish(factory, job, result=result)
    finally:
        if owned_client:
            client.close()
    logger.info("evaluation_attempt_finished id=%s attempt=%s", job.id, job.attempt)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if not get_settings().database_url.startswith("postgresql"):
        raise SystemExit("Worker requires PostgreSQL for concurrent queue locking")
    while True:
        try:
            run_once()
        except Exception:
            # Never log submission data, sandbox response bodies, credentials or SQL parameters.
            logger.error("worker_iteration_failed; lease recovery will retry")
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            break
        time.sleep(1)


if __name__ == "__main__":
    main()
