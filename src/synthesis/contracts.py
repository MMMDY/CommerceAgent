"""Strict provenance and content contracts for synthetic eval candidates."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.harness.schema import EvalMessage


class SyntheticCaseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,127}$")
    locale: Literal["zh-CN"]
    task_type: Literal["long_tail_response_v1", "safety_response_v2"]
    messages: tuple[EvalMessage, ...] = Field(min_length=1, max_length=8)
    context: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    forbidden_tools: tuple[str, ...] = ()
    tags: tuple[str, ...] = Field(min_length=1, max_length=16)
    source: dict[str, Any] = Field(default_factory=dict)
    seed_family: str = Field(min_length=1, max_length=128)
    generator: str = Field(min_length=1, max_length=128)
    prompt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    license: str = Field(min_length=1, max_length=128)
    review_status: Literal["candidate", "approved", "rejected"] = "candidate"
    risk_level: Literal["low", "medium", "high", "unknown"]

    @field_validator("messages", mode="after")
    @classmethod
    def reject_sensitive_text(cls, value: tuple[EvalMessage, ...]) -> tuple[EvalMessage, ...]:
        serialized = json.dumps([item.model_dump() for item in value], ensure_ascii=False)
        if _contains_sensitive(serialized):
            raise ValueError("synthetic candidate contains sensitive data")
        return value

    @model_validator(mode="after")
    def validate_risk_contract(self) -> SyntheticCaseCandidate:
        if self.task_type == "safety_response_v2":
            if self.risk_level != "high":
                raise ValueError("safety candidates must be high risk")
            if not self.forbidden_tools:
                raise ValueError("safety candidates require forbidden tools")
        if self.task_type == "long_tail_response_v1" and self.risk_level == "high":
            raise ValueError("high-risk cases belong in the safety dataset")
        return self

    @property
    def content_hash(self) -> str:
        payload = [message.model_dump(mode="json") for message in self.messages]
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(serialized.encode()).hexdigest()}"


class SyntheticDatasetError(ValueError):
    """A candidate batch failed a local quality gate."""


def _contains_sensitive(value: str) -> bool:
    import re

    patterns = (
        r"(?i)(api[_-]?key|authorization|password|secret)\s*[:=]",
        r"(?<!\d)(?:\+?86[- ]?)?1\d{10}(?!\d)",
        r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)",
    )
    return any(re.search(pattern, value) for pattern in patterns)


__all__ = ["SyntheticCaseCandidate", "SyntheticDatasetError"]
