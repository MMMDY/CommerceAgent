"""Versioned, browser-safe safety decision contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from src.protocols import RequestRiskLevel
from src.safety.taxonomy import SafetyCategory, SafetySeverity


class SafetyDisposition(StrEnum):
    CONTINUE = "continue"
    DEESCALATE = "deescalate"
    HANDOFF = "handoff"
    SHADOW = "shadow"


class SafetyAssessment(BaseModel):
    """The only safety facts allowed across the orchestration boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    category: SafetyCategory
    severity: SafetySeverity
    risk_level: RequestRiskLevel
    reason_code: str = Field(min_length=1, max_length=64)
    hard_block: bool
    disposition: SafetyDisposition
    safe_next_step: str = Field(min_length=1, max_length=128)
    detector_version: str = Field(min_length=1, max_length=64)
    matched: bool


__all__ = ["SafetyAssessment", "SafetyCategory", "SafetyDisposition", "SafetySeverity"]
