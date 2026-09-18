"""Strict contracts for static evaluation cases and normalized traces."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from src.harness.track_catalog import is_registered_track
from src.protocols import Contract


class EvalMessage(Contract):
    role: Literal["user", "assistant", "system", "tool"]
    content: str = Field(min_length=1, max_length=8000)


class ExpectedOutcome(Contract):
    model_config = ConfigDict(extra="forbid", frozen=True)
    values: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> ExpectedOutcome:
        return cls(values=raw)


class EvalCase(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,127}$")
    locale: Literal["zh-CN"]
    task_type: str = Field(min_length=1, max_length=64)
    messages: tuple[EvalMessage, ...]
    context: dict[str, Any] = Field(default_factory=dict)
    expected: ExpectedOutcome
    forbidden_tools: tuple[str, ...] = ()
    tags: tuple[str, ...]
    source: dict[str, Any]
    # Synthetic datasets carry provenance beside the common case contract.
    # These fields are intentionally not part of RuntimeCaseInput, so the
    # runtime cannot use generation/review metadata as an execution hint.
    seed_family: str | None = Field(default=None, min_length=1, max_length=128)
    generator: str | None = Field(default=None, min_length=1, max_length=128)
    prompt_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    license: str | None = Field(default=None, min_length=1, max_length=128)
    review_status: Literal["candidate", "approved", "rejected"] | None = None
    risk_level: Literal["low", "medium", "high", "unknown"] | None = None

    @model_validator(mode="after")
    def validate_synthetic_provenance(self) -> EvalCase:
        synthetic = self.task_type in {"long_tail_response_v1", "safety_response_v2"}
        provenance = (
            self.seed_family,
            self.generator,
            self.prompt_hash,
            self.license,
            self.review_status,
            self.risk_level,
        )
        if synthetic and any(value is None for value in provenance):
            raise ValueError("synthetic cases require complete provenance")
        if not synthetic and any(value is not None for value in provenance):
            raise ValueError("synthetic provenance is not allowed on core cases")
        if self.task_type == "safety_response_v2" and self.risk_level != "high":
            raise ValueError("safety cases must be high risk")
        if self.task_type == "long_tail_response_v1" and self.risk_level == "high":
            raise ValueError("long-tail cases cannot be high risk")
        return self

    @field_validator("task_type")
    @classmethod
    def validate_registered_track(cls, value: str) -> str:
        if not is_registered_track(value):
            raise ValueError("unknown evaluation track")
        return value

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> EvalCase:
        raw = dict(raw)
        expected = raw.pop("expected")
        return cls(expected=ExpectedOutcome.from_raw(expected), **raw)


class RuntimeCaseInput(Contract):
    """The evaluation fields that a candidate Runtime is allowed to observe.

    Gold outcomes, forbidden-tool assertions, tags, source metadata, and track
    labels intentionally do not cross this boundary.
    """

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,127}$")
    locale: Literal["zh-CN"]
    messages: tuple[EvalMessage, ...]


class NormalizedTrace(Contract):
    case_id: str
    run_id: str | None = None
    route: str | None = None
    intent: str | None = None
    next_action: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    tools_called: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    response: str = ""
    status: Literal["complete", "wait_user", "wait_human", "fail"]


class HardEvalResult(Contract):
    case_id: str
    passed: bool
    hard_fail_reasons: tuple[str, ...] = ()
    dimensions: dict[str, bool] = Field(default_factory=dict)
