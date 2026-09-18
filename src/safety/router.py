"""Safety-first routing boundary."""

from __future__ import annotations

from dataclasses import dataclass

from src.protocols import RequestRiskLevel
from src.safety.contracts import SafetyAssessment, SafetyDisposition
from src.safety.detector import detect
from src.safety.taxonomy import SafetySeverity
from src.safety.triage import LLMRiskTriage


@dataclass(frozen=True, slots=True)
class SafetyRoute:
    assessment: SafetyAssessment
    effective_disposition: SafetyDisposition
    shadow_only: bool


class SafetyRouter:
    """Run deterministic P0 checks before business routing or Skill lookup."""

    def __init__(self, *, enabled: bool = False, triage: LLMRiskTriage | None = None) -> None:
        self.enabled = enabled
        self._triage = triage

    def route(self, content: str) -> SafetyRoute:
        assessment = detect(content)
        # Hard blocks are never disabled by the feature flag.
        if assessment.hard_block:
            return SafetyRoute(assessment, SafetyDisposition.HANDOFF, False)
        if self.enabled and self._triage is not None:
            semantic = self._triage.classify(content)
            if semantic is not None and semantic.risk_level in {
                RequestRiskLevel.MEDIUM,
                RequestRiskLevel.HIGH,
            }:
                assessment = assessment.model_copy(
                    update={
                        "category": semantic.category,
                        "severity": SafetySeverity.P1,
                        "risk_level": semantic.risk_level,
                        "reason_code": "SEMANTIC_RISK_TRIAGE",
                        "disposition": SafetyDisposition.HANDOFF,
                        "safe_next_step": "暂停自动处理并转人工核验",
                        "matched": True,
                    }
                )
                return SafetyRoute(assessment, SafetyDisposition.HANDOFF, False)
        if not self.enabled:
            return SafetyRoute(assessment, SafetyDisposition.SHADOW, True)
        return SafetyRoute(assessment, assessment.disposition, False)


__all__ = ["SafetyRoute", "SafetyRouter"]
