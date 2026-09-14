"""Recovery of a readonly loop must continue from its latest checkpoint only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.agent.loop import AgentLoop
from src.agent.validation import DecisionBoundary, DecisionValidator
from src.models.gateway import DeterministicFakeModel
from src.orchestration.engine import OrchestrationEngine
from src.orchestration.pipeline import StepPipeline
from src.orchestration.workflows import WorkflowDefinition, WorkflowRegistry
from src.protocols import (
    Decision,
    DecisionType,
    DomainEvent,
    PromptView,
    RetryPolicy,
    RunContext,
    RunStatus,
    ToolContext,
    ToolResult,
    ToolRisk,
    ToolSpec,
)
from src.tools.executor import ToolExecutor
from src.tools.fake import DeterministicFakeToolAdapter
from src.tools.registry import ToolRegistry


class _DurableCheckpoints:
    def __init__(self) -> None:
        self.latest: RunContext | None = None
        self.events: list[DomainEvent] = []

    def checkpoint(
        self,
        *,
        context: RunContext,
        status: RunStatus,
        next_step: str,
        state: dict[str, object],
        events: tuple[DomainEvent, ...],
    ) -> int:
        del next_step
        version = context.checkpoint_version + 1
        self.latest = context.model_copy(
            update={
                "status": status,
                "state": state,
                "step_count": context.step_count + 1,
                "checkpoint_version": version,
            }
        )
        self.events.extend(events)
        return version

    def resume(self, *, run_id: object, tenant_id: str) -> RunContext | None:
        if (
            self.latest is None
            or self.latest.run_id != run_id
            or self.latest.tenant_id != tenant_id
        ):
            return None
        return self.latest


class _PromptBuilder:
    def build(self, *, context: RunContext) -> PromptView:
        return PromptView(
            system_policy_version="policy-1",
            workflow_id=context.workflow_id,
            workflow_version=context.workflow_version,
            current_step="lookup",
            allowed_decisions=(DecisionType.CALL_TOOL.value, DecisionType.RESPOND.value),
            conversation=(),
            known_slots={},
            required_slots=(),
            allowed_tools=("tool_a",),
            evidence_ids=(),
            remaining_steps=6 - context.step_count,
        )


def _context() -> RunContext:
    return RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="tenant",
        actor_id="actor",
        workflow_id="readonly",
        workflow_version="1",
        status=RunStatus.RUNNING_READONLY,
    )


def _boundary() -> DecisionBoundary:
    return DecisionBoundary(
        route="readonly",
        allowed_types=frozenset({DecisionType.CALL_TOOL, DecisionType.RESPOND}),
        allowed_tools=frozenset({"tool_a"}),
        trusted_evidence_ids=frozenset(),
    )


def _tool_context(context: RunContext) -> ToolContext:
    return ToolContext(
        request_id=uuid4(),
        run_id=context.run_id,
        conversation_id=context.conversation_id,
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        scopes=("read",),
    )


def _tool_spec() -> ToolSpec:
    return ToolSpec(
        name="tool_a",
        version="1",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.READ_ONLY,
        required_scopes=("read",),
        timeout_ms=1000,
        retry_policy=RetryPolicy(max_attempts=1),
        model_visible=True,
    )


def _loop(model: DeterministicFakeModel, adapter: DeterministicFakeToolAdapter) -> AgentLoop:
    return AgentLoop(
        model=model,
        validator=DecisionValidator(),
        registry=ToolRegistry((_tool_spec(),)),
        executor=ToolExecutor({"tool_a": adapter}),
    )


def test_resume_after_checkpoint_does_not_repeat_completed_tool_or_events() -> None:
    context = _context()
    checkpoints = _DurableCheckpoints()
    adapter = DeterministicFakeToolAdapter(
        (ToolResult(tool_name="tool_a", tool_version="1", data={}),)
    )
    first_loop = _loop(
        DeterministicFakeModel(
            (
                Decision(
                    type=DecisionType.CALL_TOOL,
                    intent="lookup",
                    route="readonly",
                    confidence=1,
                    tool="tool_a",
                    args={},
                ),
            )
        ),
        adapter,
    )
    first_pipeline = StepPipeline(
        step_executor=first_loop.step_executor,
        checkpoints=checkpoints,
        prompt_builder=_PromptBuilder(),
    )
    first_pipeline.advance(
        context=context,
        boundary=_boundary(),
        tool_context=_tool_context(context),
        deadline_at=datetime.now(UTC) + timedelta(seconds=2),
    )

    engine = OrchestrationEngine(
        loop=first_loop,
        workflows=WorkflowRegistry((WorkflowDefinition("readonly", "1", ("lookup",)),)),
        checkpoints=checkpoints,
    )
    recovered = engine.resume(run_id=context.run_id, tenant_id=context.tenant_id)
    assert recovered.step_count == recovered.checkpoint_version == 1
    assert len(adapter.calls) == 1
    first_event_count = len(checkpoints.events)

    resumed_loop = _loop(
        DeterministicFakeModel(
            (
                Decision(
                    type=DecisionType.RESPOND,
                    intent="lookup",
                    route="readonly",
                    confidence=1,
                    response="done",
                ),
            )
        ),
        adapter,
    )
    resumed_pipeline = StepPipeline(
        step_executor=resumed_loop.step_executor,
        checkpoints=checkpoints,
        prompt_builder=_PromptBuilder(),
    )
    result = resumed_loop.run(
        context=recovered,
        pipeline=resumed_pipeline,
        boundary=_boundary(),
        tool_context=_tool_context(recovered),
        deadline_at=datetime.now(UTC) + timedelta(seconds=2),
    )

    assert result.context.status is RunStatus.COMPLETED
    assert result.context.step_count == result.context.checkpoint_version == 2
    assert len(adapter.calls) == 1
    assert len(checkpoints.events) == first_event_count + 1
