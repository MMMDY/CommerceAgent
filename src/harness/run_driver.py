"""Case-isolated driver around the project Runtime boundary.

The driver deliberately knows nothing about a case's expected answer: gold data
is passed only to the hard evaluator after the Runtime has completed.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from src.agent.loop import AgentLoop
from src.agent.validation import DecisionBoundary
from src.harness.hard_eval import evaluate
from src.harness.runtime import FixtureManager, RuntimeTrace, TraceAdapter
from src.harness.schema import EvalCase, HardEvalResult, NormalizedTrace, RuntimeCaseInput
from src.protocols import PromptView, RunContext, StepStatus, ToolContext

if TYPE_CHECKING:
    from src.orchestration.pipeline import StepPipeline


class CaseRuntime(Protocol):
    """The minimal Runtime surface that the static Harness is allowed to call."""

    def execute_case(
        self,
        *,
        case: RuntimeCaseInput,
        fixture: dict[str, object],
        timeout_seconds: float,
        cancelled: Callable[[], bool],
    ) -> RuntimeTrace: ...


@dataclass(frozen=True, slots=True)
class AgentLoopPlan:
    context: RunContext
    prompt: PromptView
    boundary: DecisionBoundary
    tool_context: ToolContext
    deadline_at: datetime
    token_budget_remaining: int | None = None
    trace_next_action: str | None = None
    pipeline: StepPipeline | None = None


class CasePlanner(Protocol):
    def plan(
        self, *, case: RuntimeCaseInput, fixture: dict[str, object], timeout_seconds: float
    ) -> AgentLoopPlan: ...


class AgentLoopCaseRuntime:
    """Connects a case planner to the project's own bounded AgentLoop."""

    def __init__(self, *, loop: AgentLoop, planner: CasePlanner) -> None:
        self._loop = loop
        self._planner = planner

    def execute_case(
        self,
        *,
        case: RuntimeCaseInput,
        fixture: dict[str, object],
        timeout_seconds: float,
        cancelled: Callable[[], bool],
    ) -> RuntimeTrace:
        plan = self._planner.plan(case=case, fixture=fixture, timeout_seconds=timeout_seconds)
        if plan.pipeline is not None:
            run = self._loop.run(
                context=plan.context,
                pipeline=plan.pipeline,
                boundary=plan.boundary,
                tool_context=plan.tool_context,
                deadline_at=plan.deadline_at,
                cancelled=cancelled,
                token_budget_remaining=plan.token_budget_remaining,
            )
            last = run.steps[-1] if run.steps else None
            decisions = tuple(step.decision for step in run.steps if step.decision is not None)
            tool_args = next(
                (
                    dict(decision.args)
                    for decision in reversed(decisions)
                    if decision.type.value == "call_tool"
                ),
                {},
            )
            return RuntimeTrace(
                route=last.decision.route if last and last.decision else None,
                intent=last.decision.intent if last and last.decision else None,
                next_action=plan.trace_next_action
                or (last.decision.type.value if last and last.decision else None),
                args=tool_args or (dict(last.decision.args) if last and last.decision else {}),
                tools_called=tuple(
                    decision.tool for decision in decisions if decision.tool is not None
                ),
                evidence_ids=last.decision.evidence_ids if last and last.decision else (),
                response=last.response if last and last.response else "",
                status=_run_trace_status(run.exit_reason),
            )
        result = self._loop.run_step(
            context=plan.context,
            prompt=plan.prompt,
            boundary=plan.boundary,
            tool_context=plan.tool_context,
            deadline_at=plan.deadline_at,
            cancelled=cancelled(),
            token_budget_remaining=plan.token_budget_remaining,
        )
        decision = result.decision
        return RuntimeTrace(
            route=decision.route if decision else None,
            intent=decision.intent if decision else None,
            next_action=plan.trace_next_action or (decision.type.value if decision else None),
            args=dict(decision.args) if decision else {},
            tools_called=(decision.tool,) if decision and decision.tool else (),
            evidence_ids=decision.evidence_ids if decision else (),
            response=result.response or "",
            status=_trace_status(result.status),
        )


@dataclass(frozen=True, slots=True)
class DrivenCase:
    trace: NormalizedTrace
    hard_eval: HardEvalResult
    runtime_error: str | None = None


class RunDriver:
    def __init__(
        self,
        *,
        runtime: CaseRuntime,
        fixtures: FixtureManager | None = None,
        traces: TraceAdapter | None = None,
    ) -> None:
        self._runtime = runtime
        self._fixtures = fixtures or FixtureManager()
        self._traces = traces or TraceAdapter()

    def run_case(
        self,
        *,
        case: EvalCase,
        timeout_seconds: float,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> DrivenCase:
        fixture = self._fixtures.create(case)
        runtime_input = RuntimeCaseInput(
            case_id=case.id,
            locale=case.locale,
            messages=case.messages,
        )
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eval-case")
        future = executor.submit(
            self._runtime.execute_case,
            case=runtime_input,
            fixture=fixture,
            timeout_seconds=timeout_seconds,
            cancelled=cancelled,
        )
        try:
            runtime_trace = future.result(timeout=timeout_seconds)
            error = None
        except FutureTimeout:
            future.cancel()
            runtime_trace = RuntimeTrace(
                route=None,
                intent=None,
                next_action=None,
                args={},
                tools_called=(),
                evidence_ids=(),
                response="",
                status="fail",
            )
            error = "runtime_timeout"
        except Exception:
            # A bad case must not abort a batch or reveal provider/raw payloads.
            runtime_trace = RuntimeTrace(
                route=None,
                intent=None,
                next_action=None,
                args={},
                tools_called=(),
                evidence_ids=(),
                response="",
                status="fail",
            )
            error = "runtime_execution_failed"
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        trace = self._traces.normalize(case_id=case.id, trace=runtime_trace)
        return DrivenCase(trace=trace, hard_eval=evaluate(case, trace), runtime_error=error)


def _trace_status(status: StepStatus) -> str:
    return {
        StepStatus.COMPLETE: "complete",
        StepStatus.WAIT_USER: "wait_user",
        StepStatus.WAIT_HUMAN: "wait_human",
        StepStatus.CONTINUE: "complete",
        StepStatus.FAIL: "fail",
    }[status]


def _run_trace_status(exit_reason: str) -> str:
    return {
        "completed": "complete",
        "waiting_user": "wait_user",
        "waiting_human": "wait_human",
        "failed": "fail",
        "cancelled": "fail",
        "expired": "fail",
    }.get(exit_reason, "fail")
