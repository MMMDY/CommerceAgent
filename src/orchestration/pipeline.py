"""Explicit, observable execution pipeline for one bounded agent step.

The pipeline owns phase ordering while ``AgentLoop`` owns model/tool semantics
and ``OrchestrationEngine`` owns lifecycle transitions and persistence.  Phase
records contain control-flow metadata only; prompts, decisions, tool arguments,
observations, and credentials are deliberately excluded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from src.agent.loop import LoopResult
from src.agent.validation import DecisionBoundary
from src.protocols import (
    DomainEvent,
    EventType,
    PromptView,
    RunContext,
    RunStatus,
    StepStatus,
    ToolContext,
)

if TYPE_CHECKING:
    from src.orchestration.engine import AdvanceResult, OrchestrationEngine


MAX_STEPS = 6


class PipelineStage(StrEnum):
    BUILD_PROMPT = "build_prompt"
    REQUEST_DECISION = "request_decision"
    VALIDATE = "validate"
    EXECUTE = "execute"
    OBSERVE = "observe"
    REDUCE = "reduce"
    CHECKPOINT = "checkpoint"
    TERMINATE = "terminate"


PIPELINE_ORDER = tuple(PipelineStage)


class StageOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class PipelineStageRecord:
    sequence: int
    stage: PipelineStage
    outcome: StageOutcome


class PipelineSequenceError(RuntimeError):
    """A runtime component emitted a phase out of the fixed order."""


class StageObserver(Protocol):
    def record(self, stage: str, *, outcome: str) -> None: ...


class PipelineJournal:
    """In-memory order guard with an optional non-authoritative observer."""

    def __init__(self, observer: Callable[[PipelineStageRecord], None] | None = None) -> None:
        self._records: list[PipelineStageRecord] = []
        self._observer = observer

    def record(self, stage: str, *, outcome: str) -> None:
        try:
            normalized_stage = PipelineStage(stage)
            normalized_outcome = StageOutcome(outcome)
        except ValueError as error:
            raise PipelineSequenceError("unknown pipeline stage record") from error
        position = len(self._records)
        if position >= len(PIPELINE_ORDER) or normalized_stage is not PIPELINE_ORDER[position]:
            expected = PIPELINE_ORDER[position].value if position < len(PIPELINE_ORDER) else "end"
            raise PipelineSequenceError(
                f"pipeline stage out of order: expected {expected}, got {normalized_stage.value}"
            )
        record = PipelineStageRecord(
            sequence=position + 1,
            stage=normalized_stage,
            outcome=normalized_outcome,
        )
        self._records.append(record)
        if self._observer is not None:
            try:
                self._observer(record)
            except Exception:
                # Telemetry consumers are not part of the execution boundary.
                pass

    def skip_remaining(self) -> None:
        while len(self._records) < len(PIPELINE_ORDER):
            self.record(
                PIPELINE_ORDER[len(self._records)].value, outcome=StageOutcome.SKIPPED.value
            )

    def records(self) -> tuple[PipelineStageRecord, ...]:
        return tuple(self._records)

    def require_complete(self) -> None:
        if len(self._records) != len(PIPELINE_ORDER):
            raise PipelineSequenceError("pipeline did not reach every phase")


class PromptBuilder(Protocol):
    def build(self, *, context: RunContext) -> PromptView: ...


class PipelineInputError(ValueError):
    """Trusted runtime inputs disagree before a model/tool call can happen."""


@dataclass(frozen=True, slots=True)
class ReducedStep:
    status: RunStatus
    next_step: str
    state: dict[str, object]
    events: tuple[DomainEvent, ...]


@dataclass(frozen=True, slots=True)
class StepPipelineResult:
    advance: AdvanceResult
    stages: tuple[PipelineStageRecord, ...]


class StepPipeline:
    """Build a trusted prompt, then drive exactly one engine step."""

    def __init__(self, *, engine: OrchestrationEngine, prompt_builder: PromptBuilder) -> None:
        self._engine = engine
        self._prompt_builder = prompt_builder

    def advance(
        self,
        *,
        context: RunContext,
        boundary: DecisionBoundary,
        tool_context: ToolContext,
        deadline_at: datetime,
        cancelled: bool = False,
        token_budget_remaining: int | None = None,
        observer: Callable[[PipelineStageRecord], None] | None = None,
    ) -> StepPipelineResult:
        journal = PipelineJournal(observer)
        try:
            prompt = self._prompt_builder.build(context=context)
            validate_step_inputs(
                context=context,
                prompt=prompt,
                boundary=boundary,
                tool_context=tool_context,
                deadline_at=deadline_at,
            )
        except Exception:
            journal.record(PipelineStage.BUILD_PROMPT.value, outcome=StageOutcome.FAILED.value)
            journal.skip_remaining()
            raise
        journal.record(PipelineStage.BUILD_PROMPT.value, outcome=StageOutcome.COMPLETED.value)
        try:
            advance = self._engine.advance(
                context=context,
                prompt=prompt,
                boundary=boundary,
                tool_context=tool_context,
                deadline_at=deadline_at,
                cancelled=cancelled,
                token_budget_remaining=token_budget_remaining,
                stage_observer=journal,
            )
        except Exception:
            journal.skip_remaining()
            raise
        journal.require_complete()
        return StepPipelineResult(advance=advance, stages=journal.records())

    def handoff(self, *, context: RunContext, reason: str) -> AdvanceResult:
        """Persist a safe readonly-loop stop after a completed checkpoint."""

        return self._engine.handoff(context=context, reason=reason)


def validate_step_inputs(
    *,
    context: RunContext,
    prompt: PromptView,
    boundary: DecisionBoundary,
    tool_context: ToolContext,
    deadline_at: datetime,
) -> None:
    """Validate all caller-controlled bindings before requesting a decision."""

    if context.status not in {RunStatus.RUNNING_READONLY, RunStatus.RUNNING_WORKFLOW}:
        raise PipelineInputError("run status cannot be advanced")
    if (prompt.workflow_id, prompt.workflow_version) != (
        context.workflow_id,
        context.workflow_version,
    ):
        raise PipelineInputError("prompt workflow does not match locked run workflow")
    if prompt.remaining_steps > MAX_STEPS - context.step_count:
        raise PipelineInputError("prompt exceeds the runtime step budget")
    allowed_decisions = frozenset(item.value for item in boundary.allowed_types)
    if frozenset(prompt.allowed_decisions) != allowed_decisions:
        raise PipelineInputError("prompt decision boundary is inconsistent")
    if frozenset(prompt.allowed_tools) != boundary.allowed_tools:
        raise PipelineInputError("prompt tool boundary is inconsistent")
    trusted_identity = (
        context.run_id,
        context.conversation_id,
        context.tenant_id,
        context.actor_id,
    )
    tool_identity = (
        tool_context.run_id,
        tool_context.conversation_id,
        tool_context.tenant_id,
        tool_context.actor_id,
    )
    if tool_identity != trusted_identity:
        raise PipelineInputError("tool context identity does not match run context")
    if tool_context.workflow_id is not None and tool_context.workflow_id != context.workflow_id:
        raise PipelineInputError("tool context workflow does not match run context")
    if (
        tool_context.workflow_version is not None
        and tool_context.workflow_version != context.workflow_version
    ):
        raise PipelineInputError("tool context workflow version does not match run context")
    if tool_context.current_step is not None and tool_context.current_step != prompt.current_step:
        raise PipelineInputError("tool context step does not match prompt")
    if deadline_at.tzinfo is None or deadline_at.utcoffset() is None:
        raise PipelineInputError("deadline must be timezone-aware")


def reduce_step(*, context: RunContext, prompt: PromptView, result: LoopResult) -> ReducedStep:
    """Pure deterministic reduction from one observation to persisted state."""

    target = _target_status(context.status, result)
    state: dict[str, object] = dict(context.state)
    state["last_step_status"] = result.status.value
    state.pop("last_step_reason", None)
    if result.reason is not None:
        state["last_step_reason"] = result.reason
    if result.execution is not None:
        tool_result = result.execution.result
        error = tool_result.error
        observation: dict[str, object] = {
            "tool_name": tool_result.tool_name,
            "tool_version": tool_result.tool_version,
            "attempts": result.execution.attempts,
            "outcome": "succeeded" if error is None else "failed",
        }
        if error is not None:
            observation["error_code"] = error.code.value
            observation["retryable"] = error.retryable
        state["last_observation"] = observation
    next_step = (
        prompt.current_step
        if target in {RunStatus.RUNNING_READONLY, RunStatus.RUNNING_WORKFLOW}
        else "terminal"
    )
    return ReducedStep(
        status=target,
        next_step=next_step,
        state=state,
        events=_events_for(result),
    )


def _target_status(current: RunStatus, result: LoopResult) -> RunStatus:
    if result.reason == "cancelled":
        return RunStatus.CANCELLED
    if result.status is StepStatus.CONTINUE:
        return current
    if result.status is StepStatus.WAIT_USER:
        return RunStatus.WAITING_USER
    if result.status is StepStatus.WAIT_HUMAN:
        return RunStatus.WAITING_HUMAN
    if result.status is StepStatus.COMPLETE:
        return RunStatus.COMPLETED
    if result.reason in {"max_steps_exceeded", "token_budget_exhausted", "deadline_exceeded"}:
        return RunStatus.WAITING_HUMAN
    return RunStatus.FAILED


def _events_for(result: LoopResult) -> tuple[DomainEvent, ...]:
    if result.execution is not None:
        tool_result = result.execution.result
        error = tool_result.error
        observed: dict[str, object] = {
            "tool_name": tool_result.tool_name,
            "tool_version": tool_result.tool_version,
            "attempts": result.execution.attempts,
            "outcome": "succeeded" if error is None else "failed",
        }
        if error is not None:
            observed["error_code"] = error.code.value
        return (
            DomainEvent(
                event_type=EventType.TOOL_CALLED,
                payload={
                    "tool_name": tool_result.tool_name,
                    "tool_version": tool_result.tool_version,
                },
            ),
            DomainEvent(event_type=EventType.TOOL_OBSERVED, payload=observed),
            DomainEvent(event_type=EventType.STEP_COMPLETED, payload={"tool_called": True}),
        )
    if result.status is StepStatus.WAIT_USER:
        return (DomainEvent(event_type=EventType.WAITING_FOR_USER, payload={}),)
    if result.status is StepStatus.FAIL:
        return (
            DomainEvent(
                event_type=EventType.FAILED,
                payload={"reason": result.reason or "failed"},
            ),
        )
    return (
        DomainEvent(
            event_type=EventType.STEP_COMPLETED,
            payload={"status": result.status.value},
        ),
    )
