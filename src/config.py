"""Runtime configuration loaded only by backend processes."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed configuration with safe defaults for import-time use."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "demo"
    app_bind: str = "0.0.0.0:8000"
    database_url: str | None = None
    database_migration_url: SecretStr | None = None
    model: str | None = None
    api_base: str | None = None
    api_key: SecretStr | None = None
    judge_model: str | None = None
    judge_api_base: str | None = None
    judge_api_key: SecretStr | None = None
    demo_mode: bool = True
    demo_actor_allowlist: str = Field(default="demo-user-001,demo-user-002")

    @property
    def demo_actors(self) -> frozenset[str]:
        return frozenset(
            actor.strip() for actor in self.demo_actor_allowlist.split(",") if actor.strip()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
