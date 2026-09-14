from __future__ import annotations

import pytest

from src.policies.engine import (
    FactCondition,
    PolicyEffect,
    PolicyEngine,
    PolicyEngineError,
    PolicyRule,
)


def _engine() -> PolicyEngine:
    return PolicyEngine(
        version="refund-policy@v1",
        allowed_facts=frozenset({"resource.owner_match", "order.delivery_age_days"}),
        rules=(
            PolicyRule(
                rule_id="refund.owner",
                applies_to="prepare_refund",
                priority=100,
                conditions=(FactCondition("resource.owner_match", "eq", True),),
                effect=PolicyEffect.ALLOW,
                reason_code="OWNER_MATCHED",
            ),
            PolicyRule(
                rule_id="refund.window",
                applies_to="prepare_refund",
                priority=200,
                conditions=(FactCondition("order.delivery_age_days", "gt", 7),),
                effect=PolicyEffect.DENY,
                reason_code="OUTSIDE_WINDOW",
            ),
        ),
    )


def test_policy_returns_highest_safety_effect_and_a_stable_fact_hash() -> None:
    engine = _engine()
    result = engine.evaluate(
        action="prepare_refund",
        facts={"resource.owner_match": True, "order.delivery_age_days": 9},
    )
    assert result.effect is PolicyEffect.DENY
    assert result.rule_ids == ("refund.window",)
    assert result.reason_code == "OUTSIDE_WINDOW"
    assert result.facts_hash.startswith("sha256:")


def test_policy_fails_closed_for_missing_or_unapproved_facts() -> None:
    engine = _engine()
    missing = engine.evaluate(action="prepare_refund", facts={"resource.owner_match": True})
    assert missing.effect is PolicyEffect.DENY
    assert missing.reason_code == "MISSING_REQUIRED_FACTS"
    with pytest.raises(PolicyEngineError, match="unapproved"):
        engine.evaluate(action="prepare_refund", facts={"made_up": True})


def test_policy_rejects_unapproved_rule_capabilities() -> None:
    with pytest.raises(PolicyEngineError, match="unapproved fact"):
        PolicyEngine(
            version="v1",
            allowed_facts=frozenset(),
            rules=(
                PolicyRule(
                    "bad", "x", 1, (FactCondition("unknown", "eq", True),), PolicyEffect.ALLOW, "x"
                ),
            ),
        )
