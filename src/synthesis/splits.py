"""Seed-family based splits for synthetic evaluation candidates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from src.synthesis.contracts import SyntheticCaseCandidate


def split_by_seed_family(
    candidates: Iterable[SyntheticCaseCandidate],
    assignments: Mapping[str, Iterable[str]],
) -> dict[str, tuple[SyntheticCaseCandidate, ...]]:
    """Partition candidates without allowing a seed family to cross splits.

    The split contract is intentionally family-level rather than case-level:
    near paraphrases generated from one seed must never be divided between
    development and test. Every observed family must be assigned exactly once.
    """

    items = tuple(candidates)
    normalized = {
        str(name): frozenset(str(family) for family in families)
        for name, families in assignments.items()
    }
    if set(normalized) != {"development", "test"}:
        raise ValueError("seed_family_splits_require_development_and_test")
    if not normalized["development"] or not normalized["test"]:
        raise ValueError("seed_family_split_must_have_two_non_empty_sides")
    if normalized["development"] & normalized["test"]:
        raise ValueError("seed_family_cannot_cross_split")

    observed = {candidate.seed_family for candidate in items}
    if None in observed or observed != normalized["development"] | normalized["test"]:
        raise ValueError("every_seed_family_must_be_assigned_once")
    return {
        split: tuple(candidate for candidate in items if candidate.seed_family in families)
        for split, families in normalized.items()
    }


__all__ = ["split_by_seed_family"]
