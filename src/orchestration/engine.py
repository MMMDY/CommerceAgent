"""Self-built orchestration around one bounded AgentLoop step."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.agent.loop import AgentLoop, LoopResult
from src.agent.validation import DecisionBoundary
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
    ) -> AdvanceResult:
        self._workflows.get(workflow_id=context.workflow_id, version=context.workflow_version)
        loop = self._loop.run_step(
            context=context,
            prompt=prompt,
            boundary=boundary,
            tool_context=tool_context,
            deadline_at=deadline_at,
            cancelled=cancelled,
            token_budget_remaining=token_budget_remaining,
        )
        target = _target_status(context.status, loop)
        require_transition(context.status, target)
        state = dict(context.state)
        state["last_step_status"] = loop.status.value
        if loop.reason is not None:
            state["last_step_reason"] = loop.reason
        next_step = (
            prompt.current_step
            if target in {RunStatus.RUNNING_READONLY, RunStatus.RUNNING_WORKFLOW}
            else "terminal"
        )
        events = (_event_for(loop),)
        version = self._checkpoints.checkpoint(
            context=context, status=target, next_step=next_step, state=state, events=events
        )
        return AdvanceResult(
            context=context.model_copy(
                update={
                    "status": target,
                    "state": state,
                    "step_count": context.step_count + 1,
                    "checkpoint_version": version,
                }
            ),
            loop=loop,
        )

    def resume(self, context: RunContext) -> RunContext:
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


def _target_status(current: RunStatus, result: LoopResult) -> RunStatus:
    if result.reason == "cancelled":
        return RunStatus.CANCELLED
    if result.status.value == "continue":
        return current
    if result.status.value == "wait_user":
        return RunStatus.WAITING_USER
    if result.status.value == "wait_human":
        return RunStatus.WAITING_HUMAN
    if result.status.value == "complete":
        return RunStatus.COMPLETED
    return RunStatus.FAILED


def _event_for(result: LoopResult) -> DomainEvent:
    if result.status.value == "wait_user":
        return DomainEvent(event_type=EventType.WAITING_FOR_USER, payload={})
    if result.status.value == "continue":
        return DomainEvent(event_type=EventType.STEP_COMPLETED, payload={"tool_called": True})
    if result.status.value == "fail":
        return DomainEvent(
            event_type=EventType.FAILED, payload={"reason": result.reason or "failed"}
        )
    return DomainEvent(event_type=EventType.STEP_COMPLETED, payload={"status": result.status.value})
