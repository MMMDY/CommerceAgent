from __future__ import annotations

from uuid import uuid4

import pytest

from src.orchestration.workflow_executor import WorkflowExecutor, WorkflowNodeResult
from src.protocols import RunContext, RunStatus


class _Checkpoints:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def checkpoint(self, **kwargs: object) -> int:
        self.calls.append(kwargs)
        return len(self.calls)


def _context(status: RunStatus = RunStatus.RUNNING_WORKFLOW) -> RunContext:
    return RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="tenant",
        actor_id="actor",
        workflow_id="refund",
        workflow_version="1",
        status=status,
    )


def test_workflow_executor_advances_only_registered_deterministic_nodes() -> None:
    checkpoints = _Checkpoints()
    executor = WorkflowExecutor(
        nodes={
            "prepare": lambda _: WorkflowNodeResult(
                status=RunStatus.WAITING_CONFIRMATION,
                next_step="commit",
                state_patch={"preview": "trusted"},
            ),
        },
        checkpoints=checkpoints,
    )

    advanced = executor.advance(context=_context(), node="prepare")

    assert advanced.context.status is RunStatus.WAITING_CONFIRMATION
    assert advanced.context.state["preview"] == "trusted"
    assert advanced.context.checkpoint_version == 1
    assert checkpoints.calls[0]["next_step"] == "commit"


def test_workflow_executor_rejects_unknown_node_or_readonly_state() -> None:
    executor = WorkflowExecutor(nodes={}, checkpoints=_Checkpoints())
    with pytest.raises(ValueError, match="workflow node"):
        executor.advance(context=_context(), node="missing")
    with pytest.raises(ValueError, match="cannot advance"):
        executor.advance(context=_context(RunStatus.RUNNING_READONLY), node="missing")
