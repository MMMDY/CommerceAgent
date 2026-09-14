from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from src.agent.loop import AgentLoop
from src.agent.validation import DecisionBoundary, DecisionValidator
from src.models.gateway import DeterministicFakeModel
from src.orchestration.pipeline import (
    PIPELINE_ORDER,
    PipelineInputError,
    PipelineStage,
    PipelineStageRecord,
    StageOutcome,
    StepPipeline,
    reduce_step,
)
from src.protocols import (
    Decision,
    DecisionType,
    EventType,
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


class _PromptBuilder:
    def __init__(self, prompt: PromptView) -> None:
        self._prompt = prompt
        self.calls: list[RunContext] = []

    def build(self, *, context: RunContext) -> PromptView:
        self.calls.append(context)
        return self._prompt


class _Checkpoints:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def checkpoint(self, **kwargs: Any) -> int:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("injected checkpoint failure")
        return len(self.calls)


def _context(*, status: RunStatus = RunStatus.RUNNING_READONLY) -> RunContext:
    return RunContext(
        run_id=uuid4(),
        conversation_id=uuid4(),
        tenant_id="tenant-a",
        actor_id="actor-a",
        workflow_id="readonly_order",
        workflow_version="1",
        status=status,
        state={"seed": "unchanged"},
    )


def _prompt(context: RunContext) -> PromptView:
    return PromptView(
        system_policy_version="policy-1",
        workflow_id=context.workflow_id,
        workflow_version=context.workflow_version,
        current_step="lookup",
        allowed_decisions=(DecisionType.CALL_TOOL.value,),
        conversation=(),
        known_slots={},
        required_slots=(),
        allowed_tools=("get_order_status",),
        evidence_ids=(),
        remaining_steps=6,
    )


def _boundary(*, route: str = "readonly_order") -> DecisionBoundary:
    return DecisionBoundary(
        route=route,
        allowed_types=frozenset({DecisionType.CALL_TOOL}),
        allowed_tools=frozenset({"get_order_status"}),
        trusted_evidence_ids=frozenset(),
    )


def _tool_context(context: RunContext) -> ToolContext:
    return ToolContext(
        request_id=uuid4(),
        run_id=context.run_id,
        conversation_id=context.conversation_id,
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        scopes=("orders:read",),
    )


def _spec() -> ToolSpec:
    return ToolSpec(
        name="get_order_status",
        version="1",
        input_schema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
        risk=ToolRisk.READ_ONLY,
        required_scopes=("orders:read",),
        timeout_ms=1_000,
        retry_policy=RetryPolicy(max_attempts=1),
        model_visible=True,
    )


def _pipeline(
    *,
    context: RunContext,
    decision: Decision,
    adapter: DeterministicFakeToolAdapter,
    checkpoints: _Checkpoints,
) -> tuple[StepPipeline, DeterministicFakeModel, PromptView]:
    prompt = _prompt(context)
    model = DeterministicFakeModel((decision,))
    loop = AgentLoop(
        model=model,
        validator=DecisionValidator(),
        registry=ToolRegistry((_spec(),)),
        executor=ToolExecutor({"get_order_status": adapter}),
    )
    return (
        StepPipeline(
            step_executor=loop.step_executor,
            checkpoints=checkpoints,
            prompt_builder=_PromptBuilder(prompt),
        ),
        model,
        prompt,
    )


def test_readonly_step_runs_the_fixed_pipeline_and_reduces_deterministically() -> None:
    context = _context()
    adapter = DeterministicFakeToolAdapter(
        (
            ToolResult(
                tool_name="get_order_status",
                tool_version="1",
                data={"status": "shipped"},
            ),
        )
    )
    checkpoints = _Checkpoints()
    pipeline, _, prompt = _pipeline(
        context=context,
        decision=Decision(
            type=DecisionType.CALL_TOOL,
            intent="order_status",
            route="readonly_order",
            confidence=1,
            tool="get_order_status",
            args={"order_id": "ORD-001"},
        ),
        adapter=adapter,
        checkpoints=checkpoints,
    )

    result = pipeline.advance(
        context=context,
        boundary=_boundary(),
        tool_context=_tool_context(context),
        deadline_at=datetime.now(UTC) + timedelta(seconds=2),
    )

    assert tuple(record.stage for record in result.stages) == PIPELINE_ORDER
    assert all(record.outcome is StageOutcome.COMPLETED for record in result.stages)
    assert [record.sequence for record in result.stages] == list(range(1, 9))
    assert len(adapter.calls) == 1
    assert result.context.status is RunStatus.RUNNING_READONLY
    assert result.context.step_count == 1
    assert result.context.state["last_observation"] == {
        "tool_name": "get_order_status",
        "tool_version": "1",
        "attempts": 1,
        "outcome": "succeeded",
    }
    assert context.state == {"seed": "unchanged"}
    assert [event.event_type for event in checkpoints.calls[0]["events"]] == [
        EventType.TOOL_CALLED,
        EventType.TOOL_OBSERVED,
        EventType.STEP_COMPLETED,
    ]

    first = reduce_step(context=context, prompt=prompt, result=result.loop)
    second = reduce_step(context=context, prompt=prompt, result=result.loop)
    assert first == second


def test_rejected_decision_never_reaches_the_tool_side_effect_boundary() -> None:
    context = _context()
    adapter = DeterministicFakeToolAdapter(
        (
            ToolResult(
                tool_name="get_order_status",
                tool_version="1",
                data={"status": "shipped"},
            ),
        )
    )
    checkpoints = _Checkpoints()
    pipeline, _, _ = _pipeline(
        context=context,
        decision=Decision(
            type=DecisionType.CALL_TOOL,
            intent="order_status",
            route="untrusted_route",
            confidence=1,
            tool="get_order_status",
            args={"order_id": "ORD-001"},
        ),
        adapter=adapter,
        checkpoints=checkpoints,
    )

    result = pipeline.advance(
        context=context,
        boundary=_boundary(),
        tool_context=_tool_context(context),
        deadline_at=datetime.now(UTC) + timedelta(seconds=2),
    )

    assert adapter.calls == []
    assert result.context.status is RunStatus.FAILED
    assert result.loop.reason == "decision_rejected"
    outcomes = {record.stage: record.outcome for record in result.stages}
    assert outcomes[PipelineStage.VALIDATE] is StageOutcome.FAILED
    assert outcomes[PipelineStage.EXECUTE] is StageOutcome.SKIPPED
    assert outcomes[PipelineStage.CHECKPOINT] is StageOutcome.COMPLETED


def test_untrusted_run_binding_fails_before_model_tool_and_checkpoint() -> None:
    context = _context(status=RunStatus.COMPLETED)
    adapter = DeterministicFakeToolAdapter(
        (
            ToolResult(
                tool_name="get_order_status",
                tool_version="1",
                data={"status": "shipped"},
            ),
        )
    )
    checkpoints = _Checkpoints()
    pipeline, model, _ = _pipeline(
        context=context,
        decision=Decision(
            type=DecisionType.CALL_TOOL,
            intent="order_status",
            route="readonly_order",
            confidence=1,
            tool="get_order_status",
            args={"order_id": "ORD-001"},
        ),
        adapter=adapter,
        checkpoints=checkpoints,
    )
    observed: list[PipelineStageRecord] = []

    with pytest.raises(PipelineInputError, match="status"):
        pipeline.advance(
            context=context,
            boundary=_boundary(),
            tool_context=_tool_context(context),
            deadline_at=datetime.now(UTC) + timedelta(seconds=2),
            observer=observed.append,
        )

    assert model.prompts == []
    assert adapter.calls == []
    assert checkpoints.calls == []
    assert tuple(record.stage for record in observed) == PIPELINE_ORDER
    assert observed[0].outcome is StageOutcome.FAILED
    assert all(record.outcome is StageOutcome.SKIPPED for record in observed[1:])


def test_checkpoint_failure_is_observable_and_never_reports_termination() -> None:
    context = _context()
    adapter = DeterministicFakeToolAdapter(
        (
            ToolResult(
                tool_name="get_order_status",
                tool_version="1",
                data={"status": "shipped"},
            ),
        )
    )
    pipeline, _, _ = _pipeline(
        context=context,
        decision=Decision(
            type=DecisionType.CALL_TOOL,
            intent="order_status",
            route="readonly_order",
            confidence=1,
            tool="get_order_status",
            args={"order_id": "ORD-001"},
        ),
        adapter=adapter,
        checkpoints=_Checkpoints(fail=True),
    )
    observed: list[PipelineStageRecord] = []

    with pytest.raises(RuntimeError, match="checkpoint"):
        pipeline.advance(
            context=context,
            boundary=_boundary(),
            tool_context=_tool_context(context),
            deadline_at=datetime.now(UTC) + timedelta(seconds=2),
            observer=observed.append,
        )

    assert observed[-2] == PipelineStageRecord(
        sequence=7,
        stage=PipelineStage.CHECKPOINT,
        outcome=StageOutcome.FAILED,
    )
    assert observed[-1] == PipelineStageRecord(
        sequence=8,
        stage=PipelineStage.TERMINATE,
        outcome=StageOutcome.SKIPPED,
    )
