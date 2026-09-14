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
    PromptView,
    RetryPolicy,
    RunContext,
    RunStatus,
    SlotSource,
    SlotValue,
    ToolContext,
    ToolResult,
    ToolRisk,
    ToolSpec,
)
from src.tools.executor import ToolExecutor
from src.tools.fake import DeterministicFakeToolAdapter
from src.tools.registry import ToolRegistry


class _Checkpoints:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def checkpoint(self, **kwargs: object) -> int:
        self.calls.append(kwargs)
        return len(self.calls)


class _PromptBuilder:
    def __init__(self) -> None:
        self.contexts: list[RunContext] = []

    def build(self, *, context: RunContext) -> PromptView:
        self.contexts.append(context)
        last_tool = context.state.get("last_observation", {}).get("tool_name", "none")
        return PromptView(
            system_policy_version="p1",
            workflow_id=context.workflow_id,
            workflow_version=context.workflow_version,
            current_step="lookup",
            allowed_decisions=(DecisionType.CALL_TOOL.value, DecisionType.RESPOND.value),
            conversation=(),
            known_slots={
                "last_tool": SlotValue(
                    value=str(last_tool), source=SlotSource.SYSTEM, verified=True
                )
            },
            required_slots=(),
            allowed_tools=("tool_a", "tool_b"),
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


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="1",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.READ_ONLY,
        required_scopes=("read",),
        timeout_ms=1000,
        retry_policy=RetryPolicy(max_attempts=1),
        model_visible=True,
    )


def test_bounded_loop_commits_each_round_and_exposes_observation_to_next_prompt() -> None:
    context = _context()
    model = DeterministicFakeModel(
        (
            Decision(
                type=DecisionType.CALL_TOOL,
                intent="lookup",
                route="readonly",
                confidence=1,
                tool="tool_a",
                args={},
            ),
            Decision(
                type=DecisionType.CALL_TOOL,
                intent="lookup",
                route="readonly",
                confidence=1,
                tool="tool_b",
                args={},
            ),
            Decision(
                type=DecisionType.RESPOND,
                intent="lookup",
                route="readonly",
                confidence=1,
                response="完成",
            ),
        )
    )
    tool_a = DeterministicFakeToolAdapter(
        (ToolResult(tool_name="tool_a", tool_version="1", data={}),)
    )
    tool_b = DeterministicFakeToolAdapter(
        (ToolResult(tool_name="tool_b", tool_version="1", data={}),)
    )
    loop = AgentLoop(
        model=model,
        validator=DecisionValidator(),
        registry=ToolRegistry((_spec("tool_a"), _spec("tool_b"))),
        executor=ToolExecutor({"tool_a": tool_a, "tool_b": tool_b}),
    )
    checkpoints = _Checkpoints()
    builder = _PromptBuilder()
    pipeline = StepPipeline(
        engine=OrchestrationEngine(
            loop=loop,
            workflows=WorkflowRegistry((WorkflowDefinition("readonly", "1", ("lookup",)),)),
            checkpoints=checkpoints,
        ),
        prompt_builder=builder,
    )
    boundary = DecisionBoundary(
        route="readonly",
        allowed_types=frozenset({DecisionType.CALL_TOOL, DecisionType.RESPOND}),
        allowed_tools=frozenset({"tool_a", "tool_b"}),
        trusted_evidence_ids=frozenset(),
    )

    result = loop.run(
        context=context,
        pipeline=pipeline,
        boundary=boundary,
        tool_context=lambda current: ToolContext(
            request_id=uuid4(),
            run_id=current.run_id,
            conversation_id=current.conversation_id,
            tenant_id=current.tenant_id,
            actor_id=current.actor_id,
            scopes=("read",),
        ),
        deadline_at=datetime.now(UTC) + timedelta(seconds=2),
    )

    assert result.context.status is RunStatus.COMPLETED
    assert result.context.step_count == 3
    assert result.exit_reason == RunStatus.COMPLETED.value
    assert len(result.steps) == 3
    assert len(checkpoints.calls) == 3
    assert len(tool_a.calls) == 1
    assert len(tool_b.calls) == 1
    assert builder.contexts[1].state["last_observation"]["tool_name"] == "tool_a"
    assert builder.contexts[2].state["last_observation"]["tool_name"] == "tool_b"
    assert model.prompts[1].known_slots["last_tool"].value == "tool_a"
