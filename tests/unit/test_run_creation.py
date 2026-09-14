from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.agent.loop import AgentLoop
from src.agent.validation import DecisionValidator
from src.models.gateway import DeterministicFakeModel
from src.orchestration.engine import OrchestrationEngine
from src.orchestration.run_creation import ExecutionMode, RunCreationSpec
from src.orchestration.workflows import WorkflowDefinition, WorkflowRegistry
from src.protocols import RunContext, RunStatus
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry


class _Checkpoints:
    def checkpoint(self, **kwargs: object) -> int:
        del kwargs
        return 1


class _RunCreations:
    def __init__(self) -> None:
        self.calls: list[tuple[RunContext, RunCreationSpec]] = []

    def create_run(self, *, context: RunContext, spec: RunCreationSpec) -> None:
        self.calls.append((context, spec))


def _context(*, version: str = "1", status: RunStatus = RunStatus.CREATED) -> RunContext:
    return RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="tenant",
        actor_id="actor",
        workflow_id="returns",
        workflow_version=version,
        status=status,
    )


def _spec(*, current_step: str = "v1_start") -> RunCreationSpec:
    return RunCreationSpec(
        execution_mode=ExecutionMode.WORKFLOW,
        policy_version="policy-v1",
        model_config_hash="sha256:deterministic_fake",
        prompt_version="prompt-v1",
        current_step=current_step,
        max_steps=5,
        deadline_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def _engine(*, creations: _RunCreations | None = None) -> OrchestrationEngine:
    return OrchestrationEngine(
        loop=AgentLoop(
            model=DeterministicFakeModel(()),
            validator=DecisionValidator(),
            registry=ToolRegistry(()),
            executor=ToolExecutor({}),
        ),
        workflows=WorkflowRegistry(
            (
                WorkflowDefinition("returns", "1", ("v1_start",)),
                WorkflowDefinition("returns", "2", ("v2_start",)),
            )
        ),
        checkpoints=_Checkpoints(),
        run_creation_store=creations,
    )


def test_engine_create_durably_uses_the_exact_selected_workflow_version() -> None:
    creations = _RunCreations()
    engine = _engine(creations=creations)
    context = _context(version="1")
    spec = _spec(current_step="v1_start")

    assert engine.create(context, spec=spec) is context
    assert creations.calls == [(context, spec)]
    assert creations.calls[0][0].workflow_version == "1"


def test_engine_create_rejects_a_model_fingerprint_other_than_the_active_gateway() -> None:
    creations = _RunCreations()
    mismatched = _spec().model_copy(update={"model_config_hash": "sha256:other"})

    with pytest.raises(ValueError, match="model configuration"):
        _engine(creations=creations).create(_context(), spec=mismatched)

    assert creations.calls == []


def test_engine_create_keeps_the_original_in_memory_call_compatible() -> None:
    context = _context()
    assert _engine().create(context) is context


def test_engine_create_requires_both_store_and_creation_spec() -> None:
    creations = _RunCreations()
    with pytest.raises(ValueError, match="creation spec"):
        _engine(creations=creations).create(_context())
    with pytest.raises(RuntimeError, match="store is unavailable"):
        _engine().create(_context(), spec=_spec())
    assert creations.calls == []


def test_engine_create_rejects_a_step_from_a_newer_workflow_version() -> None:
    creations = _RunCreations()
    with pytest.raises(ValueError, match="locked workflow"):
        _engine(creations=creations).create(
            _context(version="1"), spec=_spec(current_step="v2_start")
        )
    assert creations.calls == []


def test_engine_create_rejects_an_expired_run_before_persistence() -> None:
    creations = _RunCreations()
    expired = _spec().model_copy(update={"deadline_at": datetime.now(UTC) - timedelta(seconds=1)})
    with pytest.raises(ValueError, match="deadline"):
        _engine(creations=creations).create(_context(), spec=expired)
    assert creations.calls == []
