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

    review_provider: str = Field(default="mock", pattern="^(mock|openai)$")
    review_external_enabled: bool = False
    review_api_key: SecretStr | None = Field(default=None, repr=False)
    review_model: str = Field(default="gpt-4.1-mini", pattern=r"^[a-zA-Z0-9._-]{1,80}$")
    review_max_output_tokens: int = Field(default=1200, ge=128, le=2000)
    review_timeout: int = Field(default=5, ge=1, le=6)
    review_user_daily_limit: int = Field(default=20, ge=1, le=100)
    review_global_daily_limit: int = Field(default=200, ge=1, le=1000)

    auth_global_per_minute: int = Field(default=20, ge=2, le=1000)
    auth_register_per_minute: int = Field(default=10, ge=1, le=100)
    auth_network_logins: int = Field(default=100, ge=5, le=1000)
    auth_network_registrations: int = Field(default=60, ge=2, le=1000)
    auth_pair_logins: int = Field(default=6, ge=2, le=100)
    auth_trusted_proxy_cidrs: str = Field(default="", max_length=1024)

    @field_validator("auth_trusted_proxy_cidrs")
    @classmethod
    def trusted_proxies(cls, value):
        from ipaddress import ip_network

        for entry in filter(None, value.split(",")):
            try:
                network = ip_network(entry.strip(), strict=True)
                if network.prefixlen == 0:
                    raise ValueError()
            except ValueError:
                raise ValueError("Trusted proxies require explicit CIDRs; trust-all is forbidden") from None
        return value

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
