"""Application settings loaded from environment variables and the repo-root `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ratelimit import Limit

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JWT_SECRET = "change-me"
MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["dev", "prod", "test"] = "dev"
    providers_config: Path = Path("config/providers.dev.yaml")

    database_url: str = "postgresql+psycopg://lingo:lingo@localhost:5433/lingo"
    # LangGraph checkpointer pool; small because the target server is low on memory.
    checkpoint_pool_max_size: int = 4

    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_expire_minutes: int = 60 * 24 * 7

    # Tenant credential encryption keys, "id:base64key[,...]" (ADR 0004 §3). Validated at
    # app startup rather than here, so tools like `app.db.migrate` run without it.
    credentials_encryption_keys: str = ""
    # Allow tenant base_urls on loopback/private networks (e.g. a local Ollama).
    provider_allow_private_networks: bool = False

    # Post-turn memory reflection (ADR 0009 §3): one extra model call per turn on the
    # tenant's `reflect` route. Off = no new memories, existing ones are still used.
    memory_reflection_enabled: bool = True

    # Scheduled background jobs (ADR 0025). Off in tests, which call the jobs directly.
    # Run one backend process only: each process would run every job.
    scheduler_enabled: bool = True
    # HTTP proxy for fetching RSS feeds only (Q41h); empty = connect directly. The proxy
    # resolves names itself, so addresses are checked once before each request and
    # redirect hop instead of on every connect (no defence against DNS rebinding).
    feed_http_proxy: str = ""

    # Where `make vocab-import` downloads ECDICT from; empty = the pinned GitHub copy.
    # A mirror must serve the same file: it is checked against the pinned sha256.
    ecdict_url: str = ""

    # Rate limits (ADR 0035), "count/window" with window in s, m or h. Login buckets count
    # failed attempts only; model buckets are per user, per minute by default.
    rate_limit_enabled: bool = True
    rate_limit_login: str = "10/15m"  # per IP + email
    rate_limit_login_ip: str = "50/15m"
    rate_limit_login_email: str = "30/15m"
    rate_limit_signup: str = "10/1h"  # per IP: register, invite codes
    rate_limit_chat: str = "20/1m"
    rate_limit_generate: str = "10/1m"
    rate_limit_tts: str = "60/1m"
    rate_limit_asr: str = "30/1m"

    # Observability (ADR 0005). Off by default: traces carry full conversation content.
    otel_tracing_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:6006/v1/traces"
    otel_service_name: str = "lingo-agent-backend"

    @field_validator(
        "rate_limit_login",
        "rate_limit_login_ip",
        "rate_limit_login_email",
        "rate_limit_signup",
        "rate_limit_chat",
        "rate_limit_generate",
        "rate_limit_tts",
        "rate_limit_asr",
    )
    @classmethod
    def _check_rate_limit(cls, value: str) -> str:
        Limit.parse(value)
        return value

    @property
    def rate_limits(self) -> dict[str, Limit]:
        """Bucket name → limit, from the `rate_limit_<bucket>` fields."""
        prefix = "rate_limit_"
        return {
            name.removeprefix(prefix): Limit.parse(value)
            for name, value in self.model_dump().items()
            if name.startswith(prefix) and isinstance(value, str)
        }

    @model_validator(mode="after")
    def _check_prod_secrets(self) -> Self:
        if self.app_env == "prod":
            if self.jwt_secret in ("", DEFAULT_JWT_SECRET):
                raise ValueError("JWT_SECRET must be set to a non-default value when APP_ENV=prod")
            # RFC 7518 §3.2: HS256 keys must be at least 256 bits.
            if len(self.jwt_secret.encode()) < MIN_JWT_SECRET_BYTES:
                raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes")
        return self

    @property
    def cookie_secure(self) -> bool:
        """Auth cookie is HTTPS-only in prod; dev runs on plain http://localhost."""
        return self.app_env == "prod"

    @property
    def providers_config_path(self) -> Path:
        """Relative paths are resolved against the repo root, not the process cwd."""
        path = self.providers_config
        return path if path.is_absolute() else REPO_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
