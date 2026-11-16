"""Versioned, data-only contract shared by the trusted worker and runner."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Case(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    label: str = Field(min_length=1, max_length=100)
    stdin: str = Field(max_length=4096)
    expected: str = Field(max_length=4096)

    @field_validator("stdin", "expected")
    @classmethod
    def bounded_bytes(cls, value):
        if len(value.encode("utf-8")) > 4096:
            raise ValueError("case input/output exceeds byte limit")
        return value


class Suite(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,80}$")
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(min_length=10, max_length=4000)
    cases: list[Case] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("case IDs must be unique")
        if sum(len(c.stdin.encode()) + len(c.expected.encode()) for c in self.cases) > 16384:
            raise ValueError("suite input/output byte budget exceeded")
        return self


class RunRequest(StrictModel):
    protocol: Literal["python-stdio-v1"] = "python-stdio-v1"
    evaluation_id: UUID
    task_id: UUID
    submission_reference: UUID
    source: str = Field(min_length=1, max_length=16000, strict=True)
    suite: Suite

    @field_validator("source")
    @classmethod
    def bounded_source(cls, value):
        if "\x00" in value or len(value.encode("utf-8")) > 32768:
            raise ValueError("source must be NUL-free and at most 32768 UTF-8 bytes")
        return value

    @model_validator(mode="after")
    def request_budget(self):
        if len(self.model_dump_json().encode()) > 120000:
            raise ValueError("runner request byte budget exceeded")
        return self


class CaseResult(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    label: str = Field(min_length=1, max_length=100)
    status: Literal["passed", "failed"]
    reason: (
        Literal[
            "wrong_answer", "runtime_error", "time_limit", "memory_limit", "output_limit", "resource_limit"
        ]
        | None
    ) = None
    duration_ms: int = Field(ge=0, le=10000, strict=True)

    @model_validator(mode="after")
    def consistent_status(self):
        if (self.status == "passed") != (self.reason is None):
            raise ValueError("failed cases require a reason; passed cases cannot have one")
        return self


class RunResult(StrictModel):
    tests_passed: int = Field(ge=0, le=8, strict=True)
    tests_total: int = Field(gt=0, le=8, strict=True)
    feedback: str = Field(default="", max_length=10000)
    case_results: list[CaseResult] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def consistent_counts(self):
        if self.tests_total != len(self.case_results) or self.tests_passed != sum(
            c.status == "passed" for c in self.case_results
        ):
            raise ValueError("counts must match case results")
        if len({c.id for c in self.case_results}) != self.tests_total:
            raise ValueError("case result IDs must be unique")
        return self
