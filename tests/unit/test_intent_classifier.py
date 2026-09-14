from __future__ import annotations

import json

import httpx
import pytest

from src.agent.intent_classifier import DeterministicFakeIntentClassifier
from src.config import Settings
from src.models.gateway import ModelGatewayError, OpenAICompatibleGateway
from src.protocols import (
    DecisionType,
    IntentClassification,
    Message,
    PromptView,
    RiskHint,
    RoutingPromptView,
)


def _settings() -> Settings:
    return Settings(
        model="m",
        api_base="https://example.test/v1",
        api_key="secret",
        classifier_model="m",
        classifier_api_base="https://example.test/v1",
        classifier_api_key="secret",
        classifier_temperature=0.1,
    )


def _prompt() -> RoutingPromptView:
    return RoutingPromptView(
        conversation=(Message(role="user", content="帮我退款"),),
        allowed_intents=("order_status", "refund_request"),
    )


def _decision_prompt() -> PromptView:
    return PromptView(
        system_policy_version="test",
        workflow_id="order_query",
        workflow_version="1",
        current_step="lookup",
        allowed_decisions=(DecisionType.RESPOND.value,),
        conversation=(),
        known_slots={},
        required_slots=(),
        allowed_tools=(),
        evidence_ids=(),
        remaining_steps=1,
    )


def test_classifier_uses_explicit_profile_at_temperature_point_one() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["Authorization"]
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"intent":"refund_request","risk_hint":"write",'
                                '"route_hint":"refund","confidence":0.98,"required_slots":["order_id"]}'
                            )
                        }
                    }
                ]
            },
        )

    gateway = OpenAICompatibleGateway(
        _settings(), httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = gateway.classify(_prompt())

    assert result.intent == "refund_request"
    assert seen["authorization"] == "Bearer secret"
    payload = seen["payload"]
    assert isinstance(payload, dict)
    assert payload["temperature"] == 0.1
    assert "execution_mode" in str(payload["messages"])
    assert gateway.classifier_config_hash != gateway.config_hash


def test_classifier_and_agent_share_connection_but_use_separate_profiles() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        if payload["temperature"] == 0.1:
            content = (
                '{"intent":"order_status","risk_hint":"read_only",'
                '"route_hint":"order_query","confidence":1,"required_slots":[]}'
            )
        else:
            content = (
                '{"type":"respond","intent":"order_status","route":"order_query",'
                '"confidence":1,"response":"ok"}'
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    gateway = OpenAICompatibleGateway(
        _settings(), httpx.Client(transport=httpx.MockTransport(handler))
    )
    gateway.classify(_prompt())
    gateway.decide(_decision_prompt())

    assert len(requests) == 2
    assert {request.url for request in requests} == {httpx.URL("https://example.test/v1/chat/completions")}
    assert requests[0].headers["Authorization"] == requests[1].headers["Authorization"]
    temperatures = {json.loads(request.content)["temperature"] for request in requests}
    assert temperatures == {0, 0.1}


@pytest.mark.parametrize(
    "content",
    (
        "not-json",
        '{"intent":"x","risk_hint":"invalid","route_hint":"x","confidence":1}',
        '{"intent":"x","risk_hint":"read_only","route_hint":"x","confidence":2}',
    ),
)
def test_classifier_rejects_invalid_candidate_without_provider_details(content: str) -> None:
    gateway = OpenAICompatibleGateway(
        _settings(),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
            )
        ),
    )

    with pytest.raises(ModelGatewayError, match="intent classification is invalid or unavailable"):
        gateway.classify(_prompt())


def test_fake_classifier_is_fifo() -> None:
    expected = IntentClassification(
        intent="order_status",
        risk_hint=RiskHint.READ_ONLY,
        route_hint="order_query",
        confidence=1,
    )
    fake = DeterministicFakeIntentClassifier((expected,))

    assert fake.classify(_prompt()) == expected
    assert fake.prompts == [_prompt()]
