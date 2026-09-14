"""Deterministic executor for write workflows; it never asks a model for a next node."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from src.orchestration.state_machine import require_transition
from src.protocols import DomainEvent, RunContext, RunStatus


class WorkflowCheckpointStore(Protocol):
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
class WorkflowNodeResult:
    status: RunStatus
    next_step: str
    state_patch: dict[str, object]
    events: tuple[DomainEvent, ...] = ()


WorkflowNode = Callable[[RunContext], WorkflowNodeResult]


@dataclass(frozen=True, slots=True)
class WorkflowAdvanceResult:
    context: RunContext
    node: str


class WorkflowExecutor:
    """Advance one registered write node and atomically checkpoint its result."""

    def __init__(
        self, *, nodes: dict[str, WorkflowNode], checkpoints: WorkflowCheckpointStore
    ) -> None:
        self._nodes = dict(nodes)
        self._checkpoints = checkpoints

    def advance(self, *, context: RunContext, node: str) -> WorkflowAdvanceResult:
        if context.status not in {
            RunStatus.RUNNING_WORKFLOW,
            RunStatus.WAITING_CONFIRMATION,
            RunStatus.COMMITTING,
            RunStatus.VERIFYING,
        }:
            raise ValueError("workflow executor cannot advance this run state")
        try:
            handler = self._nodes[node]
        except KeyError as error:
            raise ValueError("workflow node is unavailable") from error
        result = handler(context)
        require_transition(context.status, result.status)
        state = dict(context.state)
        state.update(result.state_patch)
        version = self._checkpoints.checkpoint(
            context=context,
            status=result.status,
            next_step=result.next_step,
            state=state,
            events=result.events,
        )
        return WorkflowAdvanceResult(
            context=context.model_copy(
                update={
                    "status": result.status,
                    "state": state,
                    "step_count": context.step_count + 1,
                    "checkpoint_version": version,
                }
            ),
            node=node,
        )
