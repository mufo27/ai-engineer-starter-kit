"""Application configuration via pydantic-settings.

All secrets come from environment / .env — never hardcoded. The app is
fail-closed: if a provider key is missing, that provider is disabled and the
router falls back to the mock provider (or returns 503 in strict mode).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ─────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    jwt_secret: str = "change-me-in-production-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = 3600

    # ── Database / cache ─────────────────────────────
    database_url: str = "postgresql+asyncpg://kit:kit_dev_password@localhost:5432/ai_kit"
    redis_url: str = "redis://localhost:6379/0"

    # ── LLM providers ────────────────────────────────
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_base_url: str = "https://api.anthropic.com"
    default_model: str = "mock"

    # Google Gemini (native generateContent API)
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com"

    # OpenAI-compatible providers (same chat-completions schema, different base_url)
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    ollama_enabled: bool = False
    ollama_base_url: str = "http://localhost:11434/v1"

    # ── Cost / budget guardrails ─────────────────────
    default_token_budget: int = 1_000_000
    alert_cost_threshold_usd: float = 50.0

    # ── Rate limits ──────────────────────────────────
    rate_limit_qps: int = 10
    rate_limit_monthly_requests: int = 100_000

    # ── Fail-closed behavior ─────────────────────────
    # When True, a request that cannot be served by a real provider returns 503
    # instead of silently using the mock provider.
    strict_provider_mode: bool = False

    # ── Langfuse (optional) ──────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def anthropic_enabled(self) -> bool:
        return bool(self.anthropic_api_key.strip())

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def groq_enabled(self) -> bool:
        return bool(self.groq_api_key.strip())

    @property
    def openrouter_enabled(self) -> bool:
        return bool(self.openrouter_api_key.strip())

    @property
    def deepseek_enabled(self) -> bool:
        return bool(self.deepseek_api_key.strip())

    @property
    def any_provider_enabled(self) -> bool:
        return (
            self.openai_enabled
            or self.anthropic_enabled
            or self.gemini_enabled
            or self.groq_enabled
            or self.openrouter_enabled
            or self.deepseek_enabled
            or self.ollama_enabled
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
