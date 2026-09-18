from __future__ import annotations

from src.protocols import RequestRiskLevel
from src.safety.router import SafetyRouter
from src.safety.taxonomy import SafetyCategory, SafetySeverity
from src.safety.triage import LLMRiskTriage


def test_semantic_high_risk_can_only_escalate_to_handoff() -> None:
    triage = LLMRiskTriage(
        lambda _input: {
            "risk_level": "high",
            "category": "privacy",
            "confidence": 0.95,
        }
    )

    routed = SafetyRouter(enabled=True, triage=triage).route("请处理这个模糊的账户请求")

    assert routed.effective_disposition.value == "handoff"
    assert routed.assessment.reason_code == "SEMANTIC_RISK_TRIAGE"
    assert routed.assessment.risk_level is RequestRiskLevel.HIGH
    assert routed.assessment.severity is SafetySeverity.P1


def test_invalid_or_low_confidence_semantic_result_does_not_override_router() -> None:
    invalid = LLMRiskTriage(lambda _input: {"risk_level": "high", "category": "bad"})
    low_confidence = LLMRiskTriage(
        lambda _input: {
            "risk_level": "high",
            "category": "privacy",
            "confidence": 0.4,
        }
    )

    for triage in (invalid, low_confidence):
        routed = SafetyRouter(enabled=True, triage=triage).route("查询我的订单")
        assert routed.assessment.category is SafetyCategory.NONE
        assert routed.assessment.reason_code == "RISK_REQUIRES_INTENT_TRIAGE"
        assert routed.effective_disposition.value == "continue"
