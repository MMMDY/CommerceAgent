from __future__ import annotations

from pathlib import Path

from src.harness.loader import CaseLoader
from src.harness.run_driver import RunDriver
from src.harness.runtime import RuntimeTrace
from src.harness.schema import EvalCase


def _case() -> EvalCase:
    return CaseLoader(Path("evals/commerce_bench_zh/cases.jsonl")).load(
        case_id="intent_add_product_001"
    )[0]


class _Runtime:
    def __init__(self) -> None:
        self.fixture: dict[str, object] | None = None

    def execute_case(
        self,
        *,
        case: EvalCase,
        fixture: dict[str, object],
        timeout_seconds: float,
        cancelled: object,
    ) -> RuntimeTrace:
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


def test_driver_isolates_a_runtime_failure_to_its_case() -> None:
    class BrokenRuntime:
        def execute_case(self, **_: object) -> RuntimeTrace:
            raise RuntimeError("provider response")

    result = RunDriver(runtime=BrokenRuntime()).run_case(case=_case(), timeout_seconds=1)
    assert result.runtime_error == "runtime_execution_failed"
    assert result.trace.status == "fail"
