from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.agent.loop import AgentLoop
from src.agent.validation import DecisionBoundary, DecisionValidator
from src.models.gateway import DeterministicFakeModel
from src.orchestration.pipeline import StepPipeline
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
        step_executor=loop.step_executor,
        checkpoints=checkpoints,
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


def test_loop_uses_conservative_charge_when_provider_omits_token_usage() -> None:
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
                type=DecisionType.RESPOND,
                intent="lookup",
                route="readonly",
                confidence=1,
                response="must not be requested",
            ),
        ),
        usage_tokens=(None,),
    )
    adapter = DeterministicFakeToolAdapter(
        (ToolResult(tool_name="tool_a", tool_version="1", data={}),)
    )
    loop = AgentLoop(
        model=model,
        validator=DecisionValidator(),
        registry=ToolRegistry((_spec("tool_a"),)),
        executor=ToolExecutor({"tool_a": adapter}),
    )
    checkpoints = _Checkpoints()
    pipeline = StepPipeline(
        step_executor=loop.step_executor,
        checkpoints=checkpoints,
        prompt_builder=_PromptBuilder(),
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
        token_budget_remaining=1,
    )

    assert result.context.status is RunStatus.WAITING_HUMAN
    assert result.context.state["last_step_reason"] == "token_budget_exhausted"
    assert len(model.prompts) == 1
    assert len(adapter.calls) == 1
    assert len(checkpoints.calls) == 2


def test_cancellation_after_model_response_prevents_tool_side_effect() -> None:
    cancelled = False

    class CancellingModel(DeterministicFakeModel):
        def decide(self, prompt: PromptView):  # type: ignore[no-untyped-def]
            nonlocal cancelled
            result = super().decide(prompt)
            cancelled = True
            return result

    context = _context()
    model = CancellingModel(
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
    )
    adapter = DeterministicFakeToolAdapter(
        (ToolResult(tool_name="tool_a", tool_version="1", data={}),)
    )
    loop = AgentLoop(
        model=model,
        validator=DecisionValidator(),
        registry=ToolRegistry((_spec("tool_a"),)),
        executor=ToolExecutor({"tool_a": adapter}),
    )
    pipeline = StepPipeline(
        step_executor=loop.step_executor,
        checkpoints=_Checkpoints(),
        prompt_builder=_PromptBuilder(),
    )

    result = loop.run(
        context=context,
        pipeline=pipeline,
        boundary=DecisionBoundary(
            route="readonly",
            allowed_types=frozenset({DecisionType.CALL_TOOL, DecisionType.RESPOND}),
            allowed_tools=frozenset({"tool_a", "tool_b"}),
            trusted_evidence_ids=frozenset(),
        ),
        tool_context=lambda current: ToolContext(
            request_id=uuid4(),
            run_id=current.run_id,
            conversation_id=current.conversation_id,
            tenant_id=current.tenant_id,
            actor_id=current.actor_id,
            scopes=("read",),
        ),
        deadline_at=datetime.now(UTC) + timedelta(seconds=2),
        cancelled=lambda: cancelled,
    )

    assert result.context.status is RunStatus.CANCELLED
    assert len(model.prompts) == 1
    assert adapter.calls == []


@pytest.mark.parametrize(
    "status",
    (
        RunStatus.WAITING_USER,
        RunStatus.WAITING_HUMAN,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.EXPIRED,
    ),
)
def test_non_running_status_exits_without_another_model_or_tool_call(status: RunStatus) -> None:
    context = _context().model_copy(update={"status": status})
    model = DeterministicFakeModel(())
    adapter = DeterministicFakeToolAdapter(())
    loop = AgentLoop(
        model=model,
        validator=DecisionValidator(),
        registry=ToolRegistry((_spec("tool_a"),)),
        executor=ToolExecutor({"tool_a": adapter}),
    )
    checkpoints = _Checkpoints()
    result = loop.run(
        context=context,
        pipeline=StepPipeline(
            step_executor=loop.step_executor,
            checkpoints=checkpoints,
            prompt_builder=_PromptBuilder(),
        ),
        boundary=DecisionBoundary(
            route="readonly",
            allowed_types=frozenset({DecisionType.CALL_TOOL, DecisionType.RESPOND}),
            allowed_tools=frozenset({"tool_a", "tool_b"}),
            trusted_evidence_ids=frozenset(),
        ),
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

    assert result.context is context
    assert result.steps == ()
    assert model.prompts == []
    assert adapter.calls == []
    assert checkpoints.calls == []


@pytest.mark.parametrize(
    ("context_update", "cancelled", "reason", "expected_status"),
    (
        ({"step_count": 6}, lambda: False, "max_steps_exceeded", RunStatus.WAITING_HUMAN),
        ({}, lambda: False, "deadline_exceeded", RunStatus.WAITING_HUMAN),
        ({}, lambda: True, "cancelled", RunStatus.CANCELLED),
    ),
)
def test_outer_loop_gates_checkpoint_a_safe_stop_before_model(
    context_update: dict[str, object],
    cancelled: object,
    reason: str,
    expected_status: RunStatus,
) -> None:
    context = _context().model_copy(update=context_update)
    model = DeterministicFakeModel(())
    loop = AgentLoop(
        model=model,
        validator=DecisionValidator(),
        registry=ToolRegistry((_spec("tool_a"),)),
        executor=ToolExecutor({"tool_a": DeterministicFakeToolAdapter(())}),
    )
    checkpoints = _Checkpoints()
    deadline = (
        datetime.now(UTC) - timedelta(seconds=1)
        if reason == "deadline_exceeded"
        else datetime.now(UTC) + timedelta(seconds=2)
    )
    result = loop.run(
        context=context,
        pipeline=StepPipeline(
            step_executor=loop.step_executor,
            checkpoints=checkpoints,
            prompt_builder=_PromptBuilder(),
        ),
        boundary=DecisionBoundary(
            route="readonly",
            allowed_types=frozenset({DecisionType.CALL_TOOL, DecisionType.RESPOND}),
            allowed_tools=frozenset({"tool_a", "tool_b"}),
            trusted_evidence_ids=frozenset(),
        ),
        tool_context=lambda current: ToolContext(
            request_id=uuid4(),
            run_id=current.run_id,
            conversation_id=current.conversation_id,
            tenant_id=current.tenant_id,
            actor_id=current.actor_id,
            scopes=("read",),
        ),
        deadline_at=deadline,
        cancelled=cancelled,  # type: ignore[arg-type]
    )

    assert result.context.status is expected_status
    assert result.context.state["last_step_reason"] == reason
    assert len(model.prompts) == 0
    assert len(checkpoints.calls) == 1


def test_equivalent_consecutive_readonly_actions_handoff_without_a_third_model_call() -> None:
    context = _context()
    decision = Decision(
        type=DecisionType.CALL_TOOL,
        intent="lookup",
        route="readonly",
        confidence=1,
        tool="tool_a",
        args={},
    )
    model = DeterministicFakeModel((decision, decision))
    adapter = DeterministicFakeToolAdapter(
        (
            ToolResult(tool_name="tool_a", tool_version="1", data={}),
            ToolResult(tool_name="tool_a", tool_version="1", data={}),
        )
    )
    loop = AgentLoop(
        model=model,
        validator=DecisionValidator(),
        registry=ToolRegistry((_spec("tool_a"),)),
        executor=ToolExecutor({"tool_a": adapter}),
    )
    checkpoints = _Checkpoints()
    result = loop.run(
        context=context,
        pipeline=StepPipeline(
            step_executor=loop.step_executor,
            checkpoints=checkpoints,
            prompt_builder=_PromptBuilder(),
        ),
        boundary=DecisionBoundary(
            route="readonly",
            allowed_types=frozenset({DecisionType.CALL_TOOL, DecisionType.RESPOND}),
            allowed_tools=frozenset({"tool_a", "tool_b"}),
            trusted_evidence_ids=frozenset(),
        ),
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

    assert result.context.status is RunStatus.WAITING_HUMAN
    assert result.context.state["last_step_reason"] == "readonly_loop_no_progress"
    assert len(model.prompts) == len(adapter.calls) == 2
    assert len(checkpoints.calls) == 3
