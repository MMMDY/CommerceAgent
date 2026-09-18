from pathlib import Path

from src.harness.loader import CaseLoader
from src.harness.skill_eval import build_skill_eval_slice


def test_skill_eval_slice_contains_target_counterexamples_and_full_regression() -> None:
    cases = CaseLoader(Path("evals/long_tail_zh/cases.jsonl")).load() + CaseLoader(
        Path("evals/safety_zh/cases.jsonl")
    ).load()

    result = build_skill_eval_slice(cases)

    assert result.target
    assert result.counterexamples
    assert len(result.full_regression) == len(cases)
    assert {case.id for case in result.target}.isdisjoint(
        {case.id for case in result.counterexamples}
    )
    assert len(result.all_cases) == len(cases)
