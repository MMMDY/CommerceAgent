from __future__ import annotations

import httpx
import pytest

from src.config import Settings
from src.models.gateway import ModelGatewayError, OpenAICompatibleGateway
from src.protocols import PromptView


def _settings(*, api_key: str = "secret") -> Settings:
    return Settings(
        model="m",
        api_base="https://example.test/v1",
        api_key=api_key,
        classifier_model="m",
        classifier_api_base="https://example.test/v1",
        classifier_api_key=api_key,
        classifier_temperature=0.1,
    )


def _prompt() -> PromptView:
    return PromptView(
        system_policy_version="p",
        workflow_id="w",
        workflow_version="1",
        current_step="s",
        allowed_decisions=("respond",),
        conversation=(),
        known_slots={},
        required_slots=(),
        allowed_tools=(),
        evidence_ids=(),
        remaining_steps=1,
    )


def test_gateway_parses_decision_without_exposing_authorization() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        assert request.headers["Authorization"] == "Bearer secret"
        payload = request.read().decode()
        assert "Required fields: type, intent, route, confidence" in payload
        assert "confirmation_token" in payload
        assert "secret" not in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"type":"respond","intent":"x","route":"r",'
                                '"confidence":1,"response":"ok"}'
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = _settings()
    result = OpenAICompatibleGateway(settings, client).decide(_prompt())
    assert result.decision.response == "ok"
    assert seen["path"] == "/v1/chat/completions"
    assert result.normalized_token_usage is not None
    assert result.normalized_token_usage.estimated is True
    assert result.normalized_token_usage.total_tokens == settings.model_max_tokens


def test_gateway_normalizes_detailed_provider_usage() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"type":"respond","intent":"x","route":"r",'
                                    '"confidence":1,"response":"ok"}'
                                )
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "total_tokens": 120,
                        "prompt_tokens_details": {"cached_tokens": 10},
                        "completion_tokens_details": {"reasoning_tokens": 5},
                    },
                },
            )
        )
    )
    result = OpenAICompatibleGateway(_settings(), client).decide(_prompt())
    assert result.normalized_token_usage is not None
    assert result.normalized_token_usage.model_dump(exclude={"schema_version"}) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_input_tokens": 10,
        "reasoning_tokens": 5,
        "total_tokens": 120,
        "estimated": False,
        "provider_usage_version": None,
    }


@pytest.mark.parametrize("usage", (None, {}, {"prompt_tokens": "100"}, {"total_tokens": -1}))
def test_gateway_marks_invalid_or_missing_usage_as_conservative_estimate(usage: object) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"type":"respond","intent":"x","route":"r",'
                                    '"confidence":1,"response":"ok"}'
                                )
                            }
                        }
                    ],
                    "usage": usage,
                },
            )
        )
    )
    result = OpenAICompatibleGateway(_settings(), client).decide(_prompt())
    assert result.normalized_token_usage is not None
    assert result.normalized_token_usage.estimated is True
    assert result.normalized_token_usage.total_tokens == _settings().model_max_tokens


def test_gateway_config_hash_does_not_depend_on_api_key() -> None:
    first = OpenAICompatibleGateway(
        _settings(api_key="first"),
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
    )
    second = OpenAICompatibleGateway(
        _settings(api_key="second"),
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
    )
    assert first.config_hash == second.config_hash
    assert "first" not in first.config_hash


def test_gateway_normalizes_http_errors_without_provider_payload() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    gateway = OpenAICompatibleGateway(
        _settings(), client
    )
    with pytest.raises(ModelGatewayError, match="model provider request failed"):
        gateway.decide(_prompt())


def test_gateway_retries_a_recoverable_5xx_once() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"type":"respond","intent":"x","route":"r",'
                                '"confidence":1,"response":"ok"}'
                            )
                        }
                    }
                ]
            },
        )

    gateway = OpenAICompatibleGateway(
        _settings(),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert gateway.decide(_prompt()).decision.response == "ok"
    assert calls == 2


def test_gateway_constrains_legacy_envelope_to_trusted_prompt_route() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"decision":"respond","rationale":"ok"}'}}]
                },
            )
        )
    )
    settings = _settings()
    result = OpenAICompatibleGateway(settings, client).decide(_prompt())
    assert result.decision.route == "w"
    assert result.decision.response == "ok"


@pytest.mark.parametrize(
    "content",
    (
        "not-json",
        '{"type":"unknown","intent":"x","route":"r","confidence":1}',
        (
            '{"type":"call_tool","intent":"x","route":"r","confidence":1,'
            '"tool_calls":[{"name":"a"},{"name":"b"}]}'
        ),
    ),
)
def test_gateway_rejects_invalid_or_multi_tool_output_after_one_repair(content: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    gateway = OpenAICompatibleGateway(
        _settings(),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ModelGatewayError, match="invalid after one repair"):
        gateway.decide(_prompt())
    assert calls == 2
