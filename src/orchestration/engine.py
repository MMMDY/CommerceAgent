"""Self-built orchestration around one bounded AgentLoop step."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID

from src.agent.loop import AgentLoop, LoopResult
from src.agent.validation import DecisionBoundary
from src.orchestration.pipeline import StageObserver, reduce_step, validate_step_inputs
from src.orchestration.state_machine import require_transition
from src.orchestration.workflows import WorkflowRegistry
from src.protocols import DomainEvent, EventType, PromptView, RunContext, RunStatus, ToolContext


class CheckpointStore(Protocol):
    """The atomic persistence boundary used after every successful loop step."""

    def checkpoint(
        self,
        *,
        context: RunContext,
        status: RunStatus,
        next_step: str,
        state: dict[str, object],
        events: tuple[DomainEvent, ...],
    ) -> int: ...


class RecoveryCheckpointStore(CheckpointStore, Protocol):
    def resume(self, *, run_id: UUID, tenant_id: str) -> RunContext | None: ...


@dataclass(frozen=True, slots=True)
class AdvanceResult:
    context: RunContext
    loop: LoopResult


class OrchestrationEngine:
    def __init__(
        self, *, loop: AgentLoop, workflows: WorkflowRegistry, checkpoints: CheckpointStore
    ) -> None:
        self._loop = loop
        self._workflows = workflows
        self._checkpoints = checkpoints

    def create(self, context: RunContext) -> RunContext:
        self._workflows.get(workflow_id=context.workflow_id, version=context.workflow_version)
        if context.status is not RunStatus.CREATED:
            raise ValueError("a new run must start in created status")
        return context

    def advance(
        self,
        *,
        context: RunContext,
        prompt: PromptView,
        boundary: DecisionBoundary,
        tool_context: ToolContext,
        deadline_at: datetime,
        cancelled: bool = False,
        token_budget_remaining: int | None = None,
        stage_observer: StageObserver | None = None,
    ) -> AdvanceResult:
        workflow = self._workflows.get(
            workflow_id=context.workflow_id, version=context.workflow_version
        )
        validate_step_inputs(
            context=context,
            prompt=prompt,
            boundary=boundary,
            tool_context=tool_context,
            deadline_at=deadline_at,
        )
        if prompt.current_step not in workflow.steps:
            raise ValueError("prompt step is not in the locked workflow")
        loop = self._loop.run_step(
            context=context,
            prompt=prompt,
            boundary=boundary,
            tool_context=tool_context,
            deadline_at=deadline_at,
            cancelled=cancelled,
            token_budget_remaining=token_budget_remaining,
            stage_observer=stage_observer,
        )
        try:
            reduced = reduce_step(context=context, prompt=prompt, result=loop)
            require_transition(context.status, reduced.status)
        except Exception:
            _record_stage(stage_observer, "reduce", "failed")
            _record_stage(stage_observer, "checkpoint", "skipped")
            _record_stage(stage_observer, "terminate", "skipped")
            raise
        _record_stage(stage_observer, "reduce", "completed")
        try:
            version = self._checkpoints.checkpoint(
                context=context,
                status=reduced.status,
                next_step=reduced.next_step,
                state=reduced.state,
                events=reduced.events,
            )
        except Exception:
            _record_stage(stage_observer, "checkpoint", "failed")
            _record_stage(stage_observer, "terminate", "skipped")
            raise
        _record_stage(stage_observer, "checkpoint", "completed")
        _record_stage(stage_observer, "terminate", "completed")
        return AdvanceResult(
            context=context.model_copy(
                update={
                    "status": reduced.status,
                    "state": reduced.state,
                    "step_count": context.step_count + 1,
                    "checkpoint_version": version,
                }
            ),
            loop=loop,
        )

    def resume(self, *, run_id: UUID, tenant_id: str) -> RunContext:
        """Reload the newest persisted context; never reconstruct it from request input."""

        try:
            context = cast(RecoveryCheckpointStore, self._checkpoints).resume(
                run_id=run_id, tenant_id=tenant_id
            )
        except AttributeError as error:
            raise RuntimeError("checkpoint store does not support recovery") from error
        if context is None:
            raise ValueError("run checkpoint is unavailable")
        self._workflows.get(workflow_id=context.workflow_id, version=context.workflow_version)
        return context

    def cancel(self, context: RunContext) -> RunContext:
        require_transition(context.status, RunStatus.CANCELLED)
        state = dict(context.state)
        state["last_step_reason"] = "cancelled"
        version = self._checkpoints.checkpoint(
            context=context,
            status=RunStatus.CANCELLED,
            next_step="terminal",
            state=state,
            events=(DomainEvent(event_type=EventType.FAILED, payload={"reason": "cancelled"}),),
        )
        return context.model_copy(
            update={"status": RunStatus.CANCELLED, "state": state, "checkpoint_version": version}
        )


def _record_stage(observer: StageObserver | None, stage: str, outcome: str) -> None:
    if observer is not None:
        observer.record(stage, outcome=outcome)
