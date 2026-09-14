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
