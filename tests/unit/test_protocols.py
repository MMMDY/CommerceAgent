from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.protocols import (
    Decision,
    DecisionType,
    RequestDomain,
    RequestRiskLevel,
    ResponsePolicy,
    RunContext,
    RunStatus,
    SlotSource,
    SlotValue,
    TokenUsage,
)


def test_contracts_round_trip_with_schema_version() -> None:
    context = RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="tenant-a",
        actor_id="actor-a",
        workflow_id="readonly",
        workflow_version="1.0",
        status=RunStatus.CREATED,
    )
    assert RunContext.model_validate_json(context.model_dump_json()) == context
    assert context.schema_version == "1.0"


def test_contracts_reject_unknown_fields_and_invalid_enums() -> None:
    with pytest.raises(ValidationError):
        SlotValue(value="x", source=SlotSource.USER, unexpected=True)
    with pytest.raises(ValidationError):
        Decision(
            type="unknown",
            intent="status",
            route="readonly",
            confidence=1,
        )


def test_decision_requires_bounded_confidence() -> None:
    with pytest.raises(ValidationError):
        Decision(type=DecisionType.RESPOND, intent="status", route="readonly", confidence=1.1)


def test_next_generation_routing_contracts_are_strict_and_round_trip() -> None:
    usage = TokenUsage(
        input_tokens=100,
        output_tokens=20,
        cached_input_tokens=10,
        reasoning_tokens=5,
        total_tokens=120,
        estimated=True,
        provider_usage_version="provider-v1",
    )
    assert usage.model_validate_json(usage.model_dump_json()) == usage
    assert RequestDomain.SOCIAL.value == "social"
    assert RequestRiskLevel.HIGH.value == "high"
    assert ResponsePolicy.CONVERSATIONAL_RESPONSE.value == "conversational_response"


@pytest.mark.parametrize(
    "field",
    ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens", "total_tokens"),
)
def test_token_usage_rejects_negative_counts(field: str) -> None:
    with pytest.raises(ValidationError):
        TokenUsage(**{field: -1})


def test_token_usage_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TokenUsage(input_tokens=1, unexpected=True)
