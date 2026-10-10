from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    vercel: bool = False
    vercel_url: str | None = None
    cron_secret: SecretStr = SecretStr("")
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    max_request_bytes: int = Field(default=65536, ge=1024, le=1048576)
    request_body_timeout_seconds: float = Field(default=10, ge=0.01, le=60)
    mutation_rate_limit: int = Field(default=300, ge=1)
    billing_provider: Literal["disabled", "sandbox"] = "disabled"
    billing_webhook_secret: SecretStr = SecretStr("")
    database_url: str = "postgresql+psycopg://nearperk:nearperk_local@localhost:55432/nearperk"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    discovery_radius_km: float = Field(default=5, ge=0.1, le=100)
    discovery_max_radius_km: float = Field(default=10, ge=0.1, le=100)
    offer_moderation_enabled: bool = True
    redemption_rate_limit: int = Field(default=100, ge=1)
    worker_poll_seconds: float = 2.0
    jwt_secret_key: SecretStr = SecretStr("local-development-only-change-this-signing-key")
    cookie_secure: bool = False
    trusted_proxy_host: str | None = None
    access_token_seconds: int = Field(default=900, ge=30, le=3600)
    refresh_token_days: int = Field(default=7, ge=1, le=30)
    login_ip_rate_limit: int = Field(default=50, ge=1)
    login_account_rate_limit: int = Field(default=10, ge=1)
    register_rate_limit: int = Field(default=10, ge=1)
    refresh_rate_limit: int = Field(default=120, ge=1)

    @field_validator("database_url", mode="before")
    @classmethod
    def psycopg_url(cls, value: str) -> str:
        # Managed providers supply standard PostgreSQL URLs; use our installed driver.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @model_validator(mode="after")
    def production_auth(self) -> Self:
        # Vercel cron targets the exact deployment host, not only the public alias.
        # This value is platform configuration, never a forwarded request header.
        if self.vercel and self.vercel_url and self.vercel_url.endswith(".vercel.app"):
            self.allowed_hosts = list(dict.fromkeys([*self.allowed_hosts, self.vercel_url]))
        if self.cron_secret.get_secret_value() and len(self.cron_secret.get_secret_value()) < 32:
            raise ValueError("CRON_SECRET must be at least 32 characters")
        if not self.allowed_hosts or any(
            not h or "*" in h or "/" in h or ":" in h or h.strip() != h for h in self.allowed_hosts
        ):
            raise ValueError("Supply explicit allowed host names, without ports or wildcards")
        for origin in self.cors_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
            ):
                raise ValueError(
                    "CORS origins must be explicit HTTP(S) origins without paths or credentials"
                )
            if self.app_env not in {"development", "test"} and parsed.scheme != "https":
                raise ValueError("Deployed CORS origins require HTTPS")
        if self.app_env not in {"development", "test"} and (
            not self.cors_origins
            or any(h in {"localhost", "127.0.0.1", "testserver"} for h in self.allowed_hosts)
        ):
            raise ValueError(
                "Deployed environments require explicit public hosts and HTTPS origins"
            )
        if self.discovery_radius_km > self.discovery_max_radius_km:
            raise ValueError("Default discovery radius cannot exceed the maximum")
        if self.billing_provider == "sandbox":
            if self.app_env not in {"development", "test"}:
                raise ValueError("Sandbox billing is prohibited in deployed environments")
            if len(self.billing_webhook_secret.get_secret_value()) < 32:
                raise ValueError("BILLING_WEBHOOK_SECRET must be at least 32 characters")
        key = self.jwt_secret_key.get_secret_value()
        if len(key) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        if self.app_env not in {"development", "test"}:
            if key.startswith("local-development") or not self.cookie_secure:
                raise ValueError(
                    "Deployed environments require a private signing key and secure cookies"
                )
        return self
