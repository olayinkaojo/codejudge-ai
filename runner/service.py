"""Authenticated control plane. Deploy natively on a dedicated gVisor runner host."""

import fcntl
import hashlib
import hmac
import os
import sqlite3
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from contracts.evaluation import CaseResult, RunRequest, RunResult
from runner.client import docker_client
from runner.config import RunnerSettings
from runner.isolation import GVisor


class Journal:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        self.path = directory / "results.sqlite"
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS results (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL)"
            )
        os.chmod(self.path, 0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=3)

    def lookup(self, key, digest):
        with self.connect() as db:
            row = db.execute("SELECT digest, result FROM results WHERE id=?", (key,)).fetchone()
        if row:
            if row[0] != digest:
                raise HTTPException(409, "Evaluation ID is bound to different immutable inputs")
            return RunResult.model_validate_json(row[1])
        return None

    def save(self, key, digest, result):
        with self.connect() as db:
            db.execute("INSERT INTO results VALUES (?, ?, ?)", (key, digest, result.model_dump_json()))


def evaluate(request, engine):
    results = []
    deadline = time.monotonic() + 55
    for case in request.suite.cases:
        outcome = engine.execute(request.source, case.stdin, deadline=deadline)
        reason = outcome.reason
        if reason is None and outcome.stdout.replace(b"\r\n", b"\n") != case.expected.encode("utf-8"):
            reason = "wrong_answer"
        results.append(
            CaseResult(
                id=case.id,
                label=case.label,
                status="failed" if reason else "passed",
                reason=reason,
                duration_ms=outcome.duration_ms,
            )
        )
    passed = sum(case.status == "passed" for case in results)
    return RunResult(
        tests_passed=passed,
        tests_total=len(results),
        case_results=results,
        feedback=f"{passed} of {len(results)} challenge tests passed. Per-case expected outputs are not returned.",
    )


def create_app(settings=None, engine=None):
    gate = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        nonlocal settings, engine
        settings = settings or RunnerSettings()
        settings.validate_secrets()
        journal = Journal(settings.state_dir)
        lock = open(settings.state_dir / "controller.lock", "a")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if engine is None:
            engine = GVisor(docker_client(settings), settings)
        app.state.journal = journal
        # Readiness remains closed until isolation checks pass; liveness can still support diagnosis.
        try:
            yield
        finally:
            lock.close()

    app = FastAPI(
        title="CodeJudge isolated runner", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # No rejected source text or secrets in responses/logs.
        return JSONResponse({"detail": "Invalid evaluation contract"}, status_code=422)

    async def bounded_body(request: Request, call_next):
        # Body is bounded at the ASGI layer below; auth runs before deserialization.
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.middleware("http")(bounded_body)

    def authenticated(authorization: str | None = Header(default=None)):
        expected = "Bearer " + settings.token.get_secret_value()
        if authorization is None or not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "Unauthorized")

    @app.get("/health")
    def health():
        return {"status": "alive"}

    @app.get("/ready", dependencies=[Depends(authenticated)])
    def ready():
        if not gate.acquire(blocking=False):
            raise HTTPException(503, "Runner busy")
        try:
            engine.verify()
        except Exception:
            raise HTTPException(503, "Isolation unavailable") from None
        finally:
            gate.release()
        return {"status": "ready", "runtime": "gvisor"}

    @app.post("/evaluate", response_model=RunResult, dependencies=[Depends(authenticated)])
    def run(payload: RunRequest, request: Request, idempotency_key: str = Header()):
        if idempotency_key != str(payload.evaluation_id):
            raise HTTPException(409, "Idempotency key must match evaluation ID")
        if not gate.acquire(blocking=False):
            raise HTTPException(429, "Runner busy")
        try:
            # Even cached results are not served while deployment isolation is unavailable.
            engine.verify()
            digest = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
            cached = request.app.state.journal.lookup(idempotency_key, digest)
            if cached:
                return cached
            result = evaluate(payload, engine)
            request.app.state.journal.save(idempotency_key, digest, result)
            return result
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Isolation unavailable; evaluation not completed") from None
        finally:
            gate.release()

    # No application imports/configuration/DB credentials in the execution service.
    return LimitBody(app)


class LimitBody:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > 131072:
                return await JSONResponse({"detail": "Request too large"}, status_code=413)(
                    scope, receive, send
                )
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

        await self.app(scope, replay, send)


app = create_app()
