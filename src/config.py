"""Runtime configuration loaded only by backend processes."""

from __future__ import annotations

from functools import lru_cache
from hmac import compare_digest

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
    model_timeout_seconds: float = 15.0
    model_max_tokens: int = 2048
    model_retry_attempts: int = Field(default=2, ge=1, le=2)
    classifier_model: str | None = None
    classifier_api_base: str | None = None
    classifier_api_key: SecretStr | None = None
    classifier_temperature: float | None = None
    classifier_max_tokens: int = Field(default=256, ge=16, le=2048)
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

    def classifier_configuration_is_valid(self) -> bool:
        """Return whether the explicit classifier aliases safely match Agent config.

        Deliberately return only a boolean: callers must not disclose which
        secret or endpoint was wrong through health responses or logs.
        """

        if (
            not self.model
            or not self.api_base
            or self.api_key is None
            or not self.classifier_model
            or not self.classifier_api_base
            or self.classifier_api_key is None
            or self.classifier_temperature is None
        ):
            return False
        return (
            compare_digest(self.model, self.classifier_model)
            and compare_digest(self.api_base, self.classifier_api_base)
            and compare_digest(
                self.api_key.get_secret_value(), self.classifier_api_key.get_secret_value()
            )
            and self.classifier_temperature == 0.1
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
