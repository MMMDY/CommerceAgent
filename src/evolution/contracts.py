"""Strict contracts shared by failure attribution and Skill lifecycle."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FailureSignal(StrEnum):
    RUN_FAILED = "run_failed"
    HUMAN_HANDOFF = "human_handoff"
    EXPIRED = "expired"
    LOW_CONFIDENCE = "low_confidence"
    USER_DOWNVOTE = "user_downvote"
    EVAL_FAIL = "eval_fail"
    COST_EXCEEDED = "cost_exceeded"
    HUMAN_REJECTED = "human_rejected"


class AttributionCategory(StrEnum):
    INTENT_ERROR = "intent_error"
    POLICY_ERROR = "policy_error"
    TOOL_ERROR = "tool_error"
    RETRIEVAL_ERROR = "retrieval_error"
    SAFETY_ERROR = "safety_error"
    MODEL_ERROR = "model_error"
    RESPONSE_ERROR = "response_error"
    UNKNOWN = "unknown"


class SkillStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    CANARY = "CANARY"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ROLLED_BACK = "ROLLED_BACK"


class FailureCaseView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    failure_id: UUID
    tenant_id: str
    signal: str
    severity: str
    source: str
    run_id: UUID | None
    eval_run_id: UUID | None = None
    case_id: str | None = None
    trace_refs: tuple[str, ...] = ()
    signals: tuple[dict[str, Any], ...] = ()
    status: str
    cluster_key: str
    summary_redacted: str = Field(max_length=2000)
    source_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    attribution: dict[str, Any] | None = None


__all__ = [
    "AttributionCategory",
    "FailureCaseView",
    "FailureSignal",
    "SkillStatus",
]
