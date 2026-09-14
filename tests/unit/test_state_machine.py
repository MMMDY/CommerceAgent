from __future__ import annotations

import pytest

from src.orchestration.state_machine import StateTransitionError, require_transition
from src.orchestration.workflows import WorkflowDefinition, WorkflowRegistry, WorkflowRegistryError
from src.protocols import RunStatus


def test_state_machine_rejects_terminal_and_illegal_transitions() -> None:
    require_transition(RunStatus.CREATED, RunStatus.ROUTING)
    with pytest.raises(StateTransitionError):
        require_transition(RunStatus.COMPLETED, RunStatus.RUNNING_READONLY)
    with pytest.raises(StateTransitionError):
        require_transition(RunStatus.CREATED, RunStatus.COMPLETED)


def test_workflow_registry_locks_exact_published_version() -> None:
    v1 = WorkflowDefinition("refund", "1", ("collect",))
    v2 = WorkflowDefinition("refund", "2", ("collect", "verify"))
    registry = WorkflowRegistry((v1, v2))
    assert registry.get(workflow_id="refund", version="1") is v1
    with pytest.raises(WorkflowRegistryError):
        registry.get(workflow_id="refund", version="3")
