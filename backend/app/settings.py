"""Application settings, read from environment variables or backend/.env.

Never log or print a Settings object in full: it holds secrets. Use `Settings.public_view()`.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_PLACEHOLDER = "change-me"


class AppEnv(StrEnum):
    development = "development"
    test = "test"
    demo = "demo"  # the hosted competition demo: real secrets, synthetic data, demo accounts
    production = "production"


class LLMMode(StrEnum):
    fixtures = "fixtures"  # replay recorded responses (tests, CI, offline demo)
    live = "live"  # call the real providers through the gateway
    deterministic = "deterministic"  # rule-based planner only, no model at all


class ChainMode(StrEnum):
    offline = "offline"  # anchors are computed and stored locally, never sent
    sepolia = "sepolia"  # anchors go to the Ethereum Sepolia testnet


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: AppEnv = AppEnv.development
    demo_mode: bool = True
    database_url: str = "sqlite:///./hishab.db"
    secret_key: SecretStr = SecretStr(_PLACEHOLDER)
    vault_key: SecretStr = SecretStr(_PLACEHOLDER)
    timezone: str = "Asia/Dhaka"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"],
        description="Comma-separated in the environment",
    )

    gemini_api_key: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    ollama_base_url: str = "http://localhost:11434/v1"
    llm_mode: LLMMode = LLMMode.fixtures

    sepolia_rpc_url: SecretStr = SecretStr("")
    sepolia_private_key: SecretStr = SecretStr("")
    chain_mode: ChainMode = ChainMode.offline

    smtp_host: str = ""
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.app_env in (AppEnv.demo, AppEnv.production):
            for name in ("secret_key", "vault_key"):
                secret = getattr(self, name).get_secret_value()
                if secret in ("", _PLACEHOLDER) or len(secret) < 32:
                    raise ValueError(f"{name} must be set to 32+ characters when deployed")
            if self.is_sqlite:
                raise ValueError("deployed environments use PostgreSQL, not SQLite")
        if self.app_env is AppEnv.production:
            if self.demo_mode:
                raise ValueError("demo_mode must be false in production")
            if self.llm_mode is LLMMode.fixtures:
                raise ValueError("llm_mode=fixtures is not allowed in production")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def public_view(self) -> dict[str, object]:
        """Settings that are safe to show (no secrets, only whether each one is set)."""
        return {
            "app_env": self.app_env.value,
            "demo_mode": self.demo_mode,
            "database": "sqlite" if self.is_sqlite else "postgresql",
            "llm_mode": self.llm_mode.value,
            "chain_mode": self.chain_mode.value,
            "gemini_key_set": bool(self.gemini_api_key.get_secret_value()),
            "groq_key_set": bool(self.groq_api_key.get_secret_value()),
            "sepolia_configured": bool(self.sepolia_rpc_url.get_secret_value()),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
