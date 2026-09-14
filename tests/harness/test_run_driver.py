from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from src.agent.loop import AgentLoop
from src.agent.validation import DecisionBoundary, DecisionValidator
from src.harness.loader import CaseLoader
from src.harness.run_driver import AgentLoopCaseRuntime, AgentLoopPlan, RunDriver
from src.harness.runtime import RuntimeTrace
from src.harness.schema import EvalCase, RuntimeCaseInput
from src.models.gateway import DeterministicFakeModel
from src.protocols import Decision, DecisionType, PromptView, RunContext, RunStatus, ToolContext
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry


def _case() -> EvalCase:
    return CaseLoader(Path("evals/commerce_bench_zh/cases.jsonl")).load(
        case_id="intent_add_product_001"
    )[0]


class _Runtime:
    def __init__(self) -> None:
        self.fixture: dict[str, object] | None = None
        self.case: RuntimeCaseInput | None = None

    def execute_case(
        self,
        *,
        case: RuntimeCaseInput,
        fixture: dict[str, object],
        timeout_seconds: float,
        cancelled: object,
    ) -> RuntimeTrace:
        self.case = case
        self.fixture = fixture
        fixture["mutated"] = True
        return RuntimeTrace(
            route="cart_management",
            intent="add_product",
            next_action=None,
            args={},
            tools_called=(),
            evidence_ids=(),
            response="ok",
            status="complete",
        )


def test_driver_passes_only_isolated_fixture_and_evaluates_after_runtime() -> None:
    case = _case()
    runtime = _Runtime()
    result = RunDriver(runtime=runtime).run_case(case=case, timeout_seconds=1)
    assert result.hard_eval.passed
    assert runtime.fixture is not case.context
    assert "mutated" not in case.context
    assert runtime.case is not None
    assert set(runtime.case.model_dump()) == {"schema_version", "case_id", "locale", "messages"}
    for evaluation_only_field in (
        "expected",
        "forbidden_tools",
        "source",
        "task_type",
        "tags",
    ):
        assert not hasattr(runtime.case, evaluation_only_field)


def test_driver_isolates_a_runtime_failure_to_its_case() -> None:
    class BrokenRuntime:
        def execute_case(self, **_: object) -> RuntimeTrace:
            raise RuntimeError("provider response")

    result = RunDriver(runtime=BrokenRuntime()).run_case(case=_case(), timeout_seconds=1)
    assert result.runtime_error == "runtime_execution_failed"
    assert result.trace.status == "fail"


def test_driver_can_drive_the_real_agent_loop_through_a_case_planner() -> None:
    class Planner:
        def plan(
            self,
            *,
            case: RuntimeCaseInput,
            fixture: dict[str, object],
            timeout_seconds: float,
        ) -> AgentLoopPlan:
            del case, fixture, timeout_seconds
            context = RunContext(
                run_id=uuid4(),
                conversation_id=uuid4(),
                tenant_id="t",
                actor_id="a",
                workflow_id="route",
                workflow_version="1",
                status=RunStatus.RUNNING_READONLY,
            )
            return AgentLoopPlan(
                context=context,
                prompt=PromptView(
                    system_policy_version="p",
                    workflow_id="route",
                    workflow_version="1",
                    current_step="answer",
                    allowed_decisions=("respond",),
                    conversation=(),
                    known_slots={},
                    required_slots=(),
                    allowed_tools=(),
                    evidence_ids=(),
                    remaining_steps=6,
                ),
                boundary=DecisionBoundary(
                    "cart_management", frozenset({DecisionType.RESPOND}), frozenset(), frozenset()
                ),
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

    runtime = AgentLoopCaseRuntime(
        loop=AgentLoop(
            model=DeterministicFakeModel(
                (
                    Decision(
                        type=DecisionType.RESPOND,
                        intent="add_product",
                        route="cart_management",
                        confidence=1,
                        response="ok",
                    ),
                )
            ),
            validator=DecisionValidator(),
            registry=ToolRegistry(()),
            executor=ToolExecutor({}),
        ),
        planner=Planner(),
    )
    assert RunDriver(runtime=runtime).run_case(case=_case(), timeout_seconds=1).hard_eval.passed
