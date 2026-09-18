"""Deterministic pre-router for content and account safety boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from src.protocols import RequestDomain, RequestRiskLevel
from src.safety.detector import detect
from src.safety.taxonomy import SafetyCategory


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    domain: RequestDomain
    risk_level: RequestRiskLevel
    reason_code: str
    hard_block: bool = False
    safety_category: SafetyCategory = SafetyCategory.NONE


def assess_request(content: str) -> RiskAssessment:
    """Classify only coarse safety facts; never select an executor."""

    text = content.strip().lower()
    safety = detect(content)
    if safety.hard_block:
        return RiskAssessment(
            domain=RequestDomain.UNKNOWN,
            risk_level=RequestRiskLevel.HIGH,
            reason_code=safety.reason_code,
            hard_block=True,
            safety_category=safety.category,
        )
    if any(marker in text for marker in ("心情很好", "开心", "夸一夸", "夸夸我", "谢谢", "你好")):
        return RiskAssessment(
            domain=RequestDomain.SOCIAL,
            risk_level=RequestRiskLevel.LOW,
            reason_code="LOW_RISK_SOCIAL",
        )
    if any(marker in text for marker in ("你能做什么", "你可以做什么", "能力", "支持哪些服务")):
        return RiskAssessment(
            domain=RequestDomain.CAPABILITY,
            risk_level=RequestRiskLevel.LOW,
            reason_code="LOW_RISK_CAPABILITY",
        )
    return RiskAssessment(
        domain=RequestDomain.UNKNOWN,
        risk_level=RequestRiskLevel.UNKNOWN,
        reason_code="RISK_REQUIRES_INTENT_TRIAGE",
    )


__all__ = ["RiskAssessment", "assess_request"]
