"""Central configuration. All values overridable via environment (12-factor).

Secrets (DB password, Gemini key) come from the environment only — in-cluster they are
injected from K8s Secrets. Nothing secret is hardcoded or committed (DESIGN.md constraints).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Temporal ---
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    task_queue: str = "order-supervisor"

    # --- App database (same Postgres that backs Temporal; separate logical db) ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "temporal"
    db_password: str = "temporal"
    db_name: str = "orderpilot"
    db_min_size: int = 1
    db_max_size: int = 5

    # --- Workflow defaults (Decision #9; per-run overridable at start) ---
    default_wake_interval_seconds: int = 60
    default_max_run_age_seconds: int = 24 * 60 * 60  # 24h

    # --- Agent (Decision #3): rules-only unless a Gemini key is present ---
    # Enabled by default, but `llm_active` still requires a key — so with no key the system runs
    # purely on rules, and simply supplying GEMINI_API_KEY turns the single LLM call site on.
    llm_enabled: bool = True
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    # --- API ---
    cors_origins: str = "*"

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def llm_active(self) -> bool:
        """LLM call site is live only when explicitly enabled AND a key is present."""
        return self.llm_enabled and bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
