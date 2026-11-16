from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: str = Field(
        default="postgresql+psycopg://codejudge:codejudge@localhost:5432/codejudge", repr=False
    )

    @field_validator("database_url")
    @classmethod
    def postgres_driver(cls, value):
        try:
            url = make_url(value)
        except (ArgumentError, ValueError):
            raise ValueError("DATABASE_URL must be a valid PostgreSQL URL") from None
        if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError("DATABASE_URL requires PostgreSQL with the installed Psycopg 3 driver")
        return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)

    token_hours: int = Field(default=24, ge=1, le=720)
    sandbox_url: str | None = None
    sandbox_token: SecretStr | None = None
    sandbox_timeout: int = Field(default=30, ge=1, le=120)
    lease_seconds: int = Field(default=180, ge=150, le=3600)
    max_attempts: int = Field(default=3, ge=1, le=10)
    allow_insecure_sandbox: bool = False

    @model_validator(mode="after")
    def secure_sandbox(self):
        if self.sandbox_url:
            from urllib.parse import urlsplit

            url = urlsplit(self.sandbox_url)
            if not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("sandbox_url must be an absolute URL without credentials, query or fragment")
            if url.scheme != "https" and not (url.scheme == "http" and self.allow_insecure_sandbox):
                raise ValueError("sandbox_url requires HTTPS (HTTP only with explicit development override)")
        return self


@lru_cache
def get_settings():
    return Settings()
