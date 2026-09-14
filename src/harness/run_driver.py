"""Case-isolated driver around the project Runtime boundary.

The driver deliberately knows nothing about a case's expected answer: gold data
is passed only to the hard evaluator after the Runtime has completed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from src.harness.hard_eval import evaluate
from src.harness.runtime import FixtureManager, RuntimeTrace, TraceAdapter
from src.harness.schema import EvalCase, HardEvalResult, NormalizedTrace


class CaseRuntime(Protocol):
    """The minimal Runtime surface that the static Harness is allowed to call."""

    def execute_case(
        self,
        *,
        case: EvalCase,
        fixture: dict[str, object],
        timeout_seconds: float,
        cancelled: Callable[[], bool],
    ) -> RuntimeTrace: ...


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
        try:
            runtime_trace = self._runtime.execute_case(
                case=case,
                fixture=fixture,
                timeout_seconds=timeout_seconds,
                cancelled=cancelled,
            )
            error = None
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
        trace = self._traces.normalize(case_id=case.id, trace=runtime_trace)
        return DrivenCase(trace=trace, hard_eval=evaluate(case, trace), runtime_error=error)
