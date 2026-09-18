"""Build bounded, paired evaluation slices for experience Skills.

The planner operates on frozen evaluation cases and never receives raw failure
conversations.  A target slice is always accompanied by counterexamples and a
full regression slice so a Skill cannot be approved from the same narrow
positive examples that inspired it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.harness.schema import EvalCase


@dataclass(frozen=True, slots=True)
class SkillEvalSlice:
    target: tuple[EvalCase, ...]
    counterexamples: tuple[EvalCase, ...]
    full_regression: tuple[EvalCase, ...]

    @property
    def all_cases(self) -> tuple[EvalCase, ...]:
        seen: set[str] = set()
        result: list[EvalCase] = []
        for case in (*self.target, *self.counterexamples, *self.full_regression):
            if case.id not in seen:
                seen.add(case.id)
                result.append(case)
        return tuple(result)


def build_skill_eval_slice(
    cases: Iterable[EvalCase],
    *,
    target_tracks: frozenset[str] = frozenset({"long_tail_response_v1"}),
    target_seed_families: frozenset[str] | None = None,
    counterexample_tracks: frozenset[str] = frozenset({"safety_response_v2"}),
) -> SkillEvalSlice:
    """Return target, counterexample and complete-regression partitions.

    ``target_seed_families`` is optional because a frozen dataset may contain
    more than one approved family.  When supplied it prevents a planner from
    accidentally evaluating an unrelated family.  The returned partitions are
    disjoint by case id and preserve input order for reproducible reports.
    """

    materialized = tuple(cases)
    if not materialized:
        raise ValueError("skill_eval_dataset_empty")
    target = tuple(
        case
        for case in materialized
        if case.task_type in target_tracks
        and (
            target_seed_families is None
            or case.seed_family in target_seed_families
        )
    )
    counterexamples = tuple(
        case for case in materialized if case.task_type in counterexample_tracks
    )
    if not target:
        raise ValueError("skill_eval_target_slice_empty")
    if not counterexamples:
        raise ValueError("skill_eval_counterexamples_missing")
    target_ids = {case.id for case in target}
    counterexample_ids = {case.id for case in counterexamples}
    if target_ids & counterexample_ids:
        raise ValueError("skill_eval_target_counterexample_overlap")
    return SkillEvalSlice(
        target=target,
        counterexamples=counterexamples,
        full_regression=materialized,
    )


__all__ = ["SkillEvalSlice", "build_skill_eval_slice"]
