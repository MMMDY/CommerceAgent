from pathlib import Path

from src.harness.deterministic_runtime import DeterministicRuntimeFactory, RuntimeFixtureLoader
from src.harness.loader import CaseLoader
from src.harness.run_driver import RunDriver


def test_all_sixty_workflow_cases_pass_hard_eval() -> None:
    root = Path(__file__).parents[2]
    cases = CaseLoader(root / "evals/commerce_bench_zh/cases.jsonl").load(track="tool_workflow")
    fixtures = RuntimeFixtureLoader(
        root / "evals/commerce_bench_zh/cases.runtime.jsonl"
    ).load()
    driver = RunDriver(runtime=DeterministicRuntimeFactory(fixtures))
    results = [driver.run_case(case=case, timeout_seconds=5) for case in cases]
    assert len(results) == 60
    assert all(result.hard_eval.passed for result in results)
    assert all(result.runtime_error is None for result in results)
