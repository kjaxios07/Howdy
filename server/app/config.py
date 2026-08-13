"""Central configuration. Every tunable lives here so behaviour is auditable in one place.

Secrets are read from files (Docker secrets) rather than environment variables:
env vars leak into `docker inspect`, crash dumps and child processes; files do not.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret(path: str, env_fallback: str | None = None) -> str:
    """Read a Docker secret from disk, falling back to an env var for local dev."""
    p = Path(path)
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    if env_fallback:
        import os

        value = os.environ.get(env_fallback)
        if value:
            return value.strip()
    raise RuntimeError(f"Missing secret: {path} (and no {env_fallback} in environment)")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HOWDY_", extra="ignore")

    # ── Environment ──────────────────────────────────────────────────────
    env: str = "production"
    base_url: str = "https://howdy.example"
    log_level: str = "INFO"
    sentry_dsn: str = ""

    # ── Datastores ───────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://howdy_app@db:5432/howdy"
    redis_url: str = "redis://cache:6379/0"

    # ── Claude ───────────────────────────────────────────────────────────
    # Sonnet is the right default here: answers come from our own verified
    # knowledge base, so we are paying for instruction-following and tone,
    # not frontier reasoning. Override with HOWDY_MODEL to compare.
    model: str = "claude-sonnet-5"
    max_tokens: int = 700

    # ── Google OAuth ─────────────────────────────────────────────────────
    google_client_id: str = ""
    google_discovery_url: str = (
        "https://accounts.google.com/.well-known/openid-configuration"
    )

    # ── Limits ───────────────────────────────────────────────────────────
    max_message_chars: int = 800
    max_history_turns: int = 8
    max_history_chars: int = 1500
    max_body_bytes: int = 32 * 1024

    rate_limit_anon: int = 10       # requests per window, unauthenticated
    rate_limit_user: int = 30       # requests per window, signed in
    rate_limit_window_s: int = 60

    # ── Sessions ─────────────────────────────────────────────────────────
    session_ttl_days: int = 30
    session_cookie: str = "__Host-hsid"

    # ── Retention ────────────────────────────────────────────────────────
    default_retention_days: int = 365
    allowed_retention_days: tuple[int, ...] = (30, 365, 0)  # 0 == keep until deleted

    # ── Secret file paths ────────────────────────────────────────────────
    kek_path: str = "/run/secrets/kek_v1"
    pepper_path: str = "/run/secrets/pepper"
    anthropic_key_path: str = "/run/secrets/anthropic_key"
    google_secret_path: str = "/run/secrets/google_client_secret"
    cookie_secret_path: str = "/run/secrets/cookie_secret"

    # ── Resolved secrets (populated in __init__) ─────────────────────────
    kek: bytes = Field(default=b"", exclude=True)
    pepper: bytes = Field(default=b"", exclude=True)
    anthropic_key: str = Field(default="", exclude=True)
    google_client_secret: str = Field(default="", exclude=True)
    cookie_secret: str = Field(default="", exclude=True)

    def load_secrets(self) -> "Settings":
        self.kek = base64.b64decode(_read_secret(self.kek_path, "HOWDY_KEK"))
        self.pepper = base64.b64decode(_read_secret(self.pepper_path, "HOWDY_PEPPER"))
        self.anthropic_key = _read_secret(self.anthropic_key_path, "ANTHROPIC_API_KEY")
        self.google_client_secret = _read_secret(
            self.google_secret_path, "GOOGLE_CLIENT_SECRET"
        )
        self.cookie_secret = _read_secret(self.cookie_secret_path, "HOWDY_COOKIE_SECRET")

        if len(self.kek) != 32:
            raise RuntimeError("KEK must decode to exactly 32 bytes (AES-256)")
        if len(self.pepper) < 32:
            raise RuntimeError("Pepper must be at least 32 bytes")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings().load_secrets()
