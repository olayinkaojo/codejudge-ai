"""Durable, request-bound reviews, independent of the execution queue."""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.auth import current_user
from app.config import get_settings
from app.db import get_db
from app.idempotency import replay, resource_id
from app.models import CodeReview, Task, User
from app.review_provider import ProviderFailure, ReviewResult, review

router = APIRouter(prefix="/reviews", tags=["code reviews"])


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID | None = None
    language: Literal["python"] = "python"
    source: str = Field(min_length=1, max_length=16000, repr=False, strict=True)
    external_consent: bool = Field(default=False, strict=True)

    @field_validator("source")
    @classmethod
    def bounded_source(cls, value):
        try:
            valid = bool(value.strip()) and len(value.encode("utf-8")) <= 32768
        except UnicodeEncodeError:
            valid = False
        if not valid or "\x00" in value:
            raise ValueError("Source must be nonempty UTF-8 text of at most 32768 bytes without NUL")
        return value.replace("\r\n", "\n").replace("\r", "\n")


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    task_id: UUID | None
    language: Literal["python"]
    provider: Literal["mock", "openai"]
    status: Literal["processing", "completed", "failed"]
    result: ReviewResult | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    expires_at: datetime


def clock():
    return datetime.now(timezone.utc)


def recover(db, owner):
    # No automatic retry after an interrupted request: it might already have incurred cost.
    db.execute(
        update(CodeReview)
        .where(
            CodeReview.owner_id == owner, CodeReview.status == "processing", CodeReview.deadline <= clock()
        )
        .values(status="failed", error="request_interrupted", completed_at=clock())
    )
    db.commit()


@router.get("/config")
def configuration(user: User = Depends(current_user)):
    settings = get_settings()
    return {
        "provider": settings.review_provider,
        "external": settings.review_provider != "mock",
        "available": settings.review_provider == "mock"
        or bool(settings.review_external_enabled and settings.review_api_key),
        "source_max_bytes": 32768,
        "source_max_chars": 16000,
        "retention_days": 30,
        "user_daily_limit": settings.review_user_daily_limit,
    }


@router.post("", status_code=201, response_model=ReviewOut)
def create(
    payload: ReviewCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    request_id: UUID | None = Header(default=None, alias="Idempotency-Key"),
):
    settings = get_settings()
    if payload.task_id and not db.scalar(
        select(Task.id).where(Task.id == payload.task_id, Task.owner_id == user.id)
    ):
        raise HTTPException(404, "Resource not found")
    source_digest = hashlib.sha256(payload.source.encode()).hexdigest()
    existing = replay(
        db,
        CodeReview,
        request_id,
        user.id,
        {"source_digest": source_digest, "task_id": payload.task_id, "language": payload.language},
    )
    if existing is not None:
        expiry = existing.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= clock():
            raise HTTPException(409, "Review has expired; start a new request")
        return existing
    if settings.review_provider != "mock":
        if not settings.review_external_enabled or not settings.review_api_key:
            raise HTTPException(503, "External review is not configured")
        if not payload.external_consent:
            raise HTTPException(422, "Explicit consent is required to send code to the external provider")
        if db.bind.dialect.name != "postgresql":
            raise HTTPException(503, "Durable provider budgets require PostgreSQL")
    # Serialize budget reservation across ALL API replicas, not just this process.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
        db.execute(text("SELECT pg_advisory_xact_lock(732347850136)"))
    now = clock()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    daily = select(func.count()).select_from(CodeReview).where(CodeReview.created_at >= day)
    global_count = db.scalar(daily)
    own_count = db.scalar(daily.where(CodeReview.owner_id == user.id))
    minute_count = db.scalar(
        select(func.count())
        .select_from(CodeReview)
        .where(CodeReview.owner_id == user.id, CodeReview.created_at >= now - timedelta(minutes=1))
    )
    if (
        global_count >= settings.review_global_daily_limit
        or own_count >= settings.review_user_daily_limit
        or minute_count >= 3
    ):
        db.rollback()
        raise HTTPException(429, "Review usage limit reached; try again later", headers={"Retry-After": "60"})
    # Bounded opportunistic physical purge; expired results are never readable.
    expired = select(CodeReview.id).where(CodeReview.expires_at <= now).limit(100)
    db.execute(delete(CodeReview).where(CodeReview.id.in_(expired)))
    record = CodeReview(
        owner_id=user.id,
        task_id=payload.task_id,
        source_digest=source_digest,
        **resource_id(request_id),
        line_count=max(1, len(payload.source.split("\n"))),
        provider=settings.review_provider,
        deadline=now + timedelta(seconds=20),
        expires_at=now + timedelta(days=30),
    )
    db.add(record)
    db.commit()  # Reserve budget even on provider failure, disconnect, or process restart.
    record_id = record.id
    try:
        result = review(payload.source, settings)
        values = {"status": "completed", "result": result, "error": None}
    except ProviderFailure as exc:
        values = {"status": "failed", "error": str(exc)}
    except Exception:
        # Do not log source, prompts, response bodies, credentials, or exception text.
        values = {"status": "failed", "error": "review_failed"}
    finished = clock()
    db.execute(
        update(CodeReview)
        .where(CodeReview.id == record_id, CodeReview.status == "processing", CodeReview.deadline > finished)
        .values(**values, completed_at=finished)
    )
    db.commit()
    recover(db, user.id)
    db.expire_all()
    return db.get(CodeReview, record_id)


@router.get("", response_model=list[ReviewOut])
def listing(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    recover(db, user.id)
    return db.scalars(
        select(CodeReview)
        .where(CodeReview.owner_id == user.id, CodeReview.expires_at > clock())
        .order_by(CodeReview.created_at.desc(), CodeReview.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.get("/{review_id}", response_model=ReviewOut)
def detail(review_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    recover(db, user.id)
    record = db.scalar(
        select(CodeReview).where(
            CodeReview.id == review_id, CodeReview.owner_id == user.id, CodeReview.expires_at > clock()
        )
    )
    if record is None:
        raise HTTPException(404, "Resource not found")
    return record
