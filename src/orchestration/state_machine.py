"""Explicit legal run-state transitions for the runtime."""

from __future__ import annotations

from src.protocols import RunStatus


class StateTransitionError(ValueError):
    """A runtime attempted an illegal lifecycle transition."""


TERMINAL = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.EXPIRED}
)
TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset({RunStatus.ROUTING, RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.ROUTING: frozenset(
        {
            RunStatus.RUNNING_READONLY,
            RunStatus.RUNNING_WORKFLOW,
            RunStatus.WAITING_HUMAN,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.RUNNING_READONLY: frozenset(
        {
            RunStatus.RUNNING_READONLY,
            RunStatus.WAITING_USER,
            RunStatus.WAITING_HUMAN,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.EXPIRED,
        }
    ),
    RunStatus.RUNNING_WORKFLOW: frozenset(
        {
            RunStatus.WAITING_USER,
            RunStatus.WAITING_CONFIRMATION,
            RunStatus.COMMITTING,
            RunStatus.WAITING_HUMAN,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.EXPIRED,
        }
    ),
    RunStatus.WAITING_USER: frozenset(
        {
            RunStatus.RUNNING_READONLY,
            RunStatus.RUNNING_WORKFLOW,
            RunStatus.WAITING_HUMAN,
            RunStatus.CANCELLED,
            RunStatus.EXPIRED,
        }
    ),
    RunStatus.WAITING_CONFIRMATION: frozenset(
        {
            RunStatus.WAITING_CONFIRMATION,
            RunStatus.COMMITTING,
            RunStatus.RUNNING_WORKFLOW,
            RunStatus.CANCELLED,
            RunStatus.EXPIRED,
        }
    ),
    RunStatus.COMMITTING: frozenset(
        {RunStatus.VERIFYING, RunStatus.WAITING_HUMAN, RunStatus.FAILED}
    ),
    RunStatus.VERIFYING: frozenset(
        {RunStatus.COMPLETED, RunStatus.WAITING_HUMAN, RunStatus.FAILED}
    ),
    RunStatus.WAITING_HUMAN: frozenset(
        {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
}


def require_transition(current: RunStatus, target: RunStatus) -> None:
    if current in TERMINAL or target not in TRANSITIONS.get(current, frozenset()):
        raise StateTransitionError(f"illegal transition: {current} -> {target}")
