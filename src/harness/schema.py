"""Strict contracts for static evaluation cases and normalized traces."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

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
    task_type: Literal[
        "intent_route",
        "tool_workflow",
        "rag_grounding",
        "scripted_clarification",
        "guardrail_handoff",
    ]
    messages: tuple[EvalMessage, ...]
    context: dict[str, Any] = Field(default_factory=dict)
    expected: ExpectedOutcome
    forbidden_tools: tuple[str, ...] = ()
    tags: tuple[str, ...]
    source: dict[str, Any]

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
