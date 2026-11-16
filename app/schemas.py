from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from contracts.evaluation import CaseResult, RunResult


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(Input):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    password: SecretStr

    @field_validator("username")
    @classmethod
    def normalize(cls, value):
        return value.lower()

    @field_validator("password")
    @classmethod
    def password_length(cls, value):
        if not 12 <= len(value.get_secret_value()) <= 128:
            raise ValueError("password must be 12 to 128 characters")
        return value


class TaskCreate(Input):
    title: str = Field(min_length=3, max_length=150)
    description: str = Field(min_length=10, max_length=20000)
    max_score: int = Field(default=100, ge=1, le=1000, strict=True)
    test_suite_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,80}$")


class EvaluationCreate(Input):
    task_id: UUID
    # Immutable submission reference; no URLs, filesystem paths, or commands.
    submission_reference: str = Field(min_length=1, max_length=256, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    description: str
    max_score: int
    test_suite_id: str | None
    created_at: datetime


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    task_id: UUID
    submission_reference: str
    status: str
    tests_passed: int | None
    tests_total: int | None
    score: float | None
    feedback: str | None
    case_results: list[CaseResult] | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class SubmissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    source: str = Field(min_length=1, max_length=16000, strict=True)

    @field_validator("source")
    @classmethod
    def source_size(cls, value):
        if "\x00" in value or len(value.encode("utf-8")) > 32768:
            raise ValueError("source must be NUL-free and at most 32768 UTF-8 bytes")
        return value


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    task_id: UUID
    created_at: datetime


# Backwards-compatible import name; the Phase 3 response now requires structured cases.
SandboxResult = RunResult
