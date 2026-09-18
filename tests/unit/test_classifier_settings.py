from __future__ import annotations

import pytest

from src.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "model": "agent-model",
        "api_base": "https://provider.test/v1",
        "api_key": "agent-secret",
        "classifier_model": "agent-model",
        "classifier_api_base": "https://provider.test/v1",
        "classifier_api_key": "agent-secret",
        "classifier_temperature": 0.1,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    "overrides",
    (
        {"classifier_model": "other-model"},
        {"classifier_api_base": "https://other.test/v1"},
        {"classifier_api_key": "other-secret"},
        {"classifier_temperature": 0.0},
        {"classifier_temperature": None},
        {"classifier_model": None},
    ),
)
def test_classifier_configuration_requires_equal_agent_connection_and_temperature(
    overrides: dict[str, object],
) -> None:
    assert not _settings(**overrides).classifier_configuration_is_valid()


def test_classifier_configuration_accepts_explicit_matching_aliases() -> None:
    assert _settings().classifier_configuration_is_valid()


def test_next_generation_feature_flags_are_disabled_by_default() -> None:
    settings = _settings()
    assert settings.enable_routing_v2 is False
    assert settings.enable_conversational_fallback is False
    assert settings.enable_safety_router_v2 is False
    assert settings.enable_failure_attribution is False
    assert settings.enable_experience_skills is False
    assert settings.enable_skill_shadow is False
    assert settings.enable_skill_canary is False


def test_next_generation_feature_flags_can_be_enabled_explicitly() -> None:
    settings = _settings(enable_routing_v2=True, enable_skill_shadow=True)
    assert settings.enable_routing_v2 is True
    assert settings.enable_skill_shadow is True
