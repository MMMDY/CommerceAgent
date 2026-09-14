from __future__ import annotations

import pytest

from src.agent.validation import DecisionBoundary, DecisionValidationError, DecisionValidator
from src.protocols import Decision, DecisionType, RetryPolicy, ToolRisk, ToolSpec
from src.tools.registry import ToolRegistry, ToolRegistryError


def _spec() -> ToolSpec:
    return ToolSpec(
        name="get_order",
        version="1",
        input_schema={
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        output_schema={},
        risk=ToolRisk.READ_ONLY,
        required_scopes=("order:read",),
        timeout_ms=100,
        retry_policy=RetryPolicy(max_attempts=2),
        model_visible=True,
    )


def _decision(**changes: object) -> Decision:
    values: dict[str, object] = {
        "type": DecisionType.CALL_TOOL,
        "intent": "order_status",
        "route": "order",
        "confidence": 1,
        "tool": "get_order",
        "args": {"order_id": "ORD-1"},
    }
    return Decision(**(values | changes))


def test_validator_rejects_system_fields_unknown_tools_and_non_tool_payloads() -> None:
    validator = DecisionValidator()
    boundary = DecisionBoundary(
        route="order",
        allowed_types=frozenset({DecisionType.CALL_TOOL}),
        allowed_tools=frozenset({"get_order"}),
        trusted_evidence_ids=frozenset(),
    )
    validator.validate(decision=_decision(), boundary=boundary, tool_spec=_spec())
    for decision in (
        _decision(args={"tenant_id": "x", "order_id": "ORD-1"}),
        _decision(tool="other"),
    ):
        with pytest.raises(DecisionValidationError):
            validator.validate(decision=decision, boundary=boundary, tool_spec=_spec())
    with pytest.raises(DecisionValidationError):
        validator.validate(
            decision=Decision(
                type=DecisionType.RESPOND,
                intent="x",
                route="order",
                confidence=1,
                response="ok",
                args={"x": 1},
            ),
            boundary=DecisionBoundary(
                route="order",
                allowed_types=frozenset({DecisionType.RESPOND}),
                allowed_tools=frozenset(),
                trusted_evidence_ids=frozenset(),
            ),
        )


def test_registry_is_frozen_by_name_and_version() -> None:
    registry = ToolRegistry((_spec(),))
    assert registry.get(name="get_order", version="1") == _spec()
    with pytest.raises(ToolRegistryError):
        ToolRegistry((_spec(), _spec()))
