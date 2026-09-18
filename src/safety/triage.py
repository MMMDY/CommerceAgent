"""Optional semantic risk triage that can only increase safety restrictions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.protocols import RequestRiskLevel
from src.safety.taxonomy import SafetyCategory


class RiskTriageOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    risk_level: RequestRiskLevel
    category: SafetyCategory
    confidence: float = Field(ge=0, le=1)


class LLMRiskTriage:
    """Validate a semantic classifier response without trusting its prose."""

    def __init__(self, request: Callable[[dict[str, Any]], Mapping[str, Any]]) -> None:
        self._request = request

    def classify(self, content: str) -> RiskTriageOutput | None:
        try:
            raw = self._request(
                {
                    "text": content[:4000],
                    "allowed_risk_levels": [item.value for item in RequestRiskLevel],
                    "allowed_categories": [item.value for item in SafetyCategory],
                }
            )
            result = RiskTriageOutput.model_validate(raw)
        except (ValidationError, TypeError, ValueError):
            return None
        return result if result.confidence >= 0.7 else None


__all__ = ["LLMRiskTriage", "RiskTriageOutput"]
