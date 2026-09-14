from __future__ import annotations

import pytest

from src.orchestration.router import IntentRouter, IntentRouteRule, RouteDecision, RouteOutcome
from src.orchestration.run_creation import ExecutionMode
from src.protocols import IntentClassification, RiskHint, ToolRisk


def _router() -> IntentRouter:
    return IntentRouter(
        (
            IntentRouteRule("order_status", ExecutionMode.READONLY_LOOP, "order_query", "1"),
            IntentRouteRule("refund_request", ExecutionMode.WORKFLOW, "refund", "1"),
        )
    )


def _candidate(
    intent: str = "order_status", risk_hint: RiskHint = RiskHint.READ_ONLY, confidence: float = 0.9
) -> IntentClassification:
    return IntentClassification(
        intent=intent,
        risk_hint=risk_hint,
        route_hint="untrusted-model-route",
        confidence=confidence,
    )


def test_router_selects_only_code_registered_target() -> None:
    decision = _router().decide(_candidate())

    assert decision.outcome is RouteOutcome.EXECUTE
    assert decision.execution_mode is ExecutionMode.READONLY_LOOP
    assert decision.workflow_id == "order_query"
    assert decision.reason_code == "ROUTE_RULE_MATCHED"


@pytest.mark.parametrize(
    "candidate,tool_risk,reason",
    (
        (_candidate(intent="unknown"), None, "UNKNOWN_INTENT"),
        (_candidate(confidence=0.79), None, "LOW_CLASSIFICATION_CONFIDENCE"),
        (_candidate(risk_hint=RiskHint.WRITE), None, "CLASSIFICATION_RISK_CONFLICT"),
        (_candidate(), ToolRisk.PREPARE, "TOOL_RISK_CONFLICT"),
    ),
)
def test_router_fails_closed_on_unknown_low_confidence_or_risk_conflict(
    candidate: IntentClassification, tool_risk: ToolRisk | None, reason: str
) -> None:
    decision = _router().decide(candidate, target_tool_risk=tool_risk)

    assert decision.outcome is RouteOutcome.HANDOFF
    assert decision.execution_mode is None
    assert decision.workflow_id is None
    assert decision.reason_code == reason


def test_router_allows_write_classification_only_for_registered_workflow() -> None:
    decision = _router().decide(_candidate("refund_request", RiskHint.WRITE))

    assert decision.outcome is RouteOutcome.EXECUTE
    assert decision.execution_mode is ExecutionMode.WORKFLOW
    assert decision.workflow_id == "refund"


def test_route_decision_rejects_partial_execute_target() -> None:
    with pytest.raises(ValueError, match="complete target"):
        RouteDecision(
            outcome=RouteOutcome.EXECUTE,
            execution_mode=ExecutionMode.READONLY_LOOP,
            reason_code="invalid",
        )
