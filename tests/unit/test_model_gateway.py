from __future__ import annotations

import httpx
import pytest

from src.config import Settings
from src.models.gateway import ModelGatewayError, OpenAICompatibleGateway
from src.protocols import PromptView


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
    settings = Settings(model="m", api_base="https://example.test/v1", api_key="secret")
    result = OpenAICompatibleGateway(settings, client).decide(_prompt())
    assert result.decision.response == "ok"
    assert seen["path"] == "/v1/chat/completions"


def test_gateway_config_hash_does_not_depend_on_api_key() -> None:
    first = OpenAICompatibleGateway(
        Settings(model="m", api_base="https://example.test/v1", api_key="first"),
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
    )
    second = OpenAICompatibleGateway(
        Settings(model="m", api_base="https://example.test/v1", api_key="second"),
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
    )
    assert first.config_hash == second.config_hash
    assert "first" not in first.config_hash


def test_gateway_normalizes_http_errors_without_provider_payload() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    gateway = OpenAICompatibleGateway(
        Settings(model="m", api_base="https://example.test/v1", api_key="secret"), client
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
        Settings(model="m", api_base="https://example.test/v1", api_key="secret"),
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
    settings = Settings(model="m", api_base="https://example.test/v1", api_key="secret")
    result = OpenAICompatibleGateway(settings, client).decide(_prompt())
    assert result.decision.route == "w"
    assert result.decision.response == "ok"
