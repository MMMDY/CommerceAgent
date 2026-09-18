from __future__ import annotations

import pytest

from src.orchestration.route_catalog import intent_route_rules
from src.orchestration.router import IntentRouter, IntentRouteRule, RouteDecision, RouteOutcome
from src.orchestration.run_creation import ExecutionMode
from src.protocols import (
    IntentClassification,
    RequestDomain,
    RequestRiskLevel,
    ResponsePolicy,
    RiskHint,
    ToolRisk,
)


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

    if reason == "LOW_CLASSIFICATION_CONFIDENCE":
        assert decision.outcome is RouteOutcome.ASK_USER
    else:
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


def test_router_allows_only_explicit_low_risk_conversational_route() -> None:
    router = IntentRouter(
        (
            IntentRouteRule(
                "social_chat",
                ExecutionMode.READONLY_LOOP,
                "conversational_response",
                "1",
                response_policy=ResponsePolicy.CONVERSATIONAL_RESPONSE,
                domain=RequestDomain.SOCIAL,
            ),
        )
    )
    candidate = IntentClassification(
        intent="social_chat",
        risk_hint=RiskHint.READ_ONLY,
        route_hint="untrusted",
        confidence=0.95,
        domain=RequestDomain.SOCIAL,
        request_risk_level=RequestRiskLevel.LOW,
    )

    decision = router.decide(candidate)

    assert decision.outcome is RouteOutcome.EXECUTE
    assert decision.response_policy is ResponsePolicy.CONVERSATIONAL_RESPONSE
    assert decision.request_domain is RequestDomain.SOCIAL


def test_router_fails_closed_when_conversational_risk_is_unknown_or_high() -> None:
    router = IntentRouter(
        (
            IntentRouteRule(
                "social_chat",
                ExecutionMode.READONLY_LOOP,
                "conversational_response",
                "1",
                response_policy=ResponsePolicy.CONVERSATIONAL_RESPONSE,
                domain=RequestDomain.SOCIAL,
            ),
        )
    )
    for risk in (RequestRiskLevel.UNKNOWN, RequestRiskLevel.HIGH):
        candidate = IntentClassification(
            intent="social_chat",
            risk_hint=RiskHint.READ_ONLY,
            route_hint="untrusted",
            confidence=0.95,
            domain=RequestDomain.SOCIAL,
            request_risk_level=risk,
        )
        assert router.decide(candidate).reason_code == "NON_LOW_RISK_CONVERSATIONAL_REQUEST"


def test_v1_and_v2_shadow_decisions_are_comparable_without_executing_shadow() -> None:
    candidate = IntentClassification(
        intent="social_chat",
        risk_hint=RiskHint.READ_ONLY,
        route_hint="untrusted",
        confidence=0.95,
        domain=RequestDomain.SOCIAL,
        request_risk_level=RequestRiskLevel.LOW,
    )

    current = IntentRouter(
        intent_route_rules(routing_v2=False, conversational_fallback=False)
    ).decide(candidate)
    shadow = IntentRouter(
        intent_route_rules(routing_v2=True, conversational_fallback=True)
    ).decide(candidate)

    assert current.outcome is RouteOutcome.HANDOFF
    assert shadow.outcome is RouteOutcome.EXECUTE
    assert shadow.workflow_id == "conversational_response"
    # The shadow result is evidence only; this test deliberately does not
    # pass it to any runtime executor.
