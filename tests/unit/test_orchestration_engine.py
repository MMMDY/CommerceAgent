from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.agent.loop import AgentLoop
from src.agent.validation import DecisionBoundary, DecisionValidator
from src.models.gateway import DeterministicFakeModel
from src.orchestration.engine import OrchestrationEngine
from src.orchestration.workflows import WorkflowDefinition, WorkflowRegistry
from src.protocols import (
    Decision,
    DecisionType,
    DomainEvent,
    PromptView,
    RunContext,
    RunStatus,
    ToolContext,
)
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry


class _Checkpoints:
    def __init__(self) -> None:
        self.calls: list[tuple[RunStatus, tuple[DomainEvent, ...]]] = []

    def checkpoint(self, **kwargs: object) -> int:
        self.calls.append((kwargs["status"], kwargs["events"]))  # type: ignore[arg-type]
        return len(self.calls)

    def resume(self, *, run_id: object, tenant_id: str) -> RunContext | None:
        del run_id, tenant_id
        return self.recovered if hasattr(self, "recovered") else None


def _context() -> RunContext:
    return RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="t",
        actor_id="a",
        workflow_id="w",
        workflow_version="1",
        status=RunStatus.RUNNING_READONLY,
    )


def _prompt() -> PromptView:
    return PromptView(
        system_policy_version="p",
        workflow_id="w",
        workflow_version="1",
        current_step="answer",
        allowed_decisions=("respond",),
        conversation=(),
        known_slots={},
        required_slots=(),
        allowed_tools=(),
        evidence_ids=(),
        remaining_steps=6,
    )


def test_engine_checkpoints_each_completed_step_and_locks_workflow_version() -> None:
    checkpoints = _Checkpoints()
    engine = OrchestrationEngine(
        loop=AgentLoop(
            model=DeterministicFakeModel(
                (
                    Decision(
                        type=DecisionType.RESPOND,
                        intent="i",
                        route="r",
                        confidence=1,
                        response="ok",
                    ),
                )
            ),
            validator=DecisionValidator(),
            registry=ToolRegistry(()),
            executor=ToolExecutor({}),
        ),
        workflows=WorkflowRegistry((WorkflowDefinition("w", "1", ("answer",)),)),
        checkpoints=checkpoints,
    )
    context = _context()
    result = engine.advance(
        context=context,
        prompt=_prompt(),
        boundary=DecisionBoundary("r", frozenset({DecisionType.RESPOND}), frozenset(), frozenset()),
        tool_context=ToolContext(
            request_id=uuid4(),
            run_id=context.run_id,
            conversation_id=context.conversation_id,
            tenant_id="t",
            actor_id="a",
            scopes=(),
        ),
        deadline_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    assert result.context.status is RunStatus.COMPLETED
    assert result.context.checkpoint_version == 1
    assert checkpoints.calls[0][0] is RunStatus.COMPLETED


def test_engine_cancel_persists_terminal_checkpoint() -> None:
    checkpoints = _Checkpoints()
    engine = OrchestrationEngine(
        loop=AgentLoop(
            model=DeterministicFakeModel(()),
            validator=DecisionValidator(),
            registry=ToolRegistry(()),
            executor=ToolExecutor({}),
        ),
        workflows=WorkflowRegistry((WorkflowDefinition("w", "1", ("answer",)),)),
        checkpoints=checkpoints,
    )
    cancelled = engine.cancel(_context())
    assert cancelled.status is RunStatus.CANCELLED
    assert checkpoints.calls[0][0] is RunStatus.CANCELLED


def test_engine_handoff_persists_a_safe_loop_guard_exit() -> None:
    checkpoints = _Checkpoints()
    engine = OrchestrationEngine(
        loop=AgentLoop(
            model=DeterministicFakeModel(()),
            validator=DecisionValidator(),
            registry=ToolRegistry(()),
            executor=ToolExecutor({}),
        ),
        workflows=WorkflowRegistry((WorkflowDefinition("w", "1", ("answer",)),)),
        checkpoints=checkpoints,
    )

    result = engine.handoff(context=_context(), reason="readonly_loop_no_progress")

    assert result.context.status is RunStatus.WAITING_HUMAN
    assert result.context.state["last_step_reason"] == "readonly_loop_no_progress"
    assert checkpoints.calls[0][0] is RunStatus.WAITING_HUMAN


def test_engine_resume_loads_context_from_checkpoint_store() -> None:
    checkpoints = _Checkpoints()
    checkpoints.recovered = _context()
    engine = OrchestrationEngine(
        loop=AgentLoop(
            model=DeterministicFakeModel(()),
            validator=DecisionValidator(),
            registry=ToolRegistry(()),
            executor=ToolExecutor({}),
        ),
        workflows=WorkflowRegistry((WorkflowDefinition("w", "1", ("answer",)),)),
        checkpoints=checkpoints,
    )
    assert (
        engine.resume(run_id=checkpoints.recovered.run_id, tenant_id="t") == checkpoints.recovered
    )
