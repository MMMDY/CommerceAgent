"""Coverage of the Phase 3 intent map."""

# ruff: noqa: E501

from src.orchestration.route_catalog import DEFAULT_INTENT_ROUTE_RULES, REQUIRED_SLOTS
from src.orchestration.router import IntentRouter
from src.protocols import IntentClassification, RiskHint


def test_phase3_catalog_covers_thirty_intents_and_human_agent_handoffs() -> None:
    assert len(DEFAULT_INTENT_ROUTE_RULES) == 30
    decision = IntentRouter(DEFAULT_INTENT_ROUTE_RULES).decide(
        IntentClassification(
            intent="human_agent", risk_hint=RiskHint.UNKNOWN, route_hint="human_agent", confidence=1.0
        )
    )
    assert decision.outcome.value == "handoff"


def test_resource_slots_are_declared_for_owner_verification() -> None:
    assert REQUIRED_SLOTS["track_order"] == ("order_id",)
