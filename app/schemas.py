from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


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


class EvaluationCreate(Input):
    task_id: UUID
    # Opaque artifact ID, never a URL/path to fetch or command to execute.
    submission_reference: str = Field(min_length=1, max_length=256, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    description: str
    max_score: int
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
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class SandboxResult(Input):
    tests_passed: int = Field(ge=0, le=1000000, strict=True)
    tests_total: int = Field(gt=0, le=1000000, strict=True)
    feedback: str = Field(default="", max_length=10000)

    @field_validator("tests_total")
    @classmethod
    def valid_counts(cls, value, info):
        if info.data.get("tests_passed", 0) > value:
            raise ValueError("tests_passed cannot exceed tests_total")
        return value
