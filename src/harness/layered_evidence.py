"""Plan-level fail-closed audit for layered evaluation evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def audit_layered_evidence(
    human_review: Mapping[str, Any],
    baseline_comparison: Mapping[str, Any],
    *,
    minimum_reviewed: int = 20,
    expected_cases: int = 300,
    expected_attempts: int = 900,
    skip_human_review: bool = False,
    waiver_reason: str | None = None,
) -> dict[str, Any]:
    """Audit layered evidence, optionally recording an explicit human-review waiver.

    A waiver never turns missing labels into human evidence.  It only removes
    the human-review item from the blocking list when the caller explicitly
    opts into the automated-only audit and supplies a reason.
    """

    if minimum_reviewed < 1:
        raise ValueError("minimum_reviewed must be positive")
    if expected_cases < 1 or expected_attempts < 1:
        raise ValueError("expected baseline sizes must be positive")
    if skip_human_review and not waiver_reason:
        raise ValueError("waiver_reason is required when human review is skipped")
    if waiver_reason is not None and not waiver_reason.strip():
        raise ValueError("waiver_reason must not be empty")

    review_stats = human_review.get("stats")
    if not isinstance(review_stats, Mapping):
        review_stats = human_review
    current = baseline_comparison.get("current")
    historical = baseline_comparison.get("historical")
    current = current if isinstance(current, Mapping) else {}
    historical = historical if isinstance(historical, Mapping) else {}

    report_status = _mapping(baseline_comparison.get("report_status"))
    hard_checks = _mapping(baseline_comparison.get("checks"))
    judge_dependent = _mapping(baseline_comparison.get("judge_dependent"))
    input_hashes = _mapping(judge_dependent.get("input_hashes"))
    final_pass = _mapping(judge_dependent.get("final_pass"))
    human_review_complete = (
            review_stats.get("status") == "complete"
            and _integer_at_least(review_stats.get("reviewed_count"), minimum_reviewed)
            and _integer_at_least(review_stats.get("selected_count"), minimum_reviewed)
            and _integer_at_least(review_stats.get("unique_selected_count"), minimum_reviewed)
            and review_stats.get("minimum_count") == minimum_reviewed
            and review_stats.get("missing_label_count", 0) == 0
            and review_stats.get("extra_label_count", 0) == 0
            and not review_stats.get("duplicate_scenario_ids", [])
            and review_stats.get("gate_pass") is True
        )
    checks = {
        "human_review_complete": human_review_complete,
        "baseline_status": (
            baseline_comparison.get("status") == "invariant_preserved"
            and baseline_comparison.get("evidence_status") == "complete"
            and baseline_comparison.get("comparison_scope") == "hard_runtime_and_judge"
        ),
        "baseline_reports_complete": (
            report_status.get("both_completed") is True
        ),
        "hard_checks_complete": (
            all(hard_checks.get(name) is True for name in (
                "dataset_hash",
                "dataset_shape",
                "track_shape",
                "hard_pass",
            ))
        ),
        "baseline_shape": all(
            _baseline_size(
                report,
                expected_cases=expected_cases,
                expected_attempts=expected_attempts,
            )
            for report in (historical, current)
        ),
        "judge_dependent_comparable": (
            judge_dependent.get("status") == "comparable"
            and judge_dependent.get("signature_match") is True
            and input_hashes.get("status") == "complete"
            and _equal_positive_ints(
                input_hashes,
                ("historical_count", "current_count", "shared_count", "matching_count"),
            )
        ),
        "final_pass_unchanged": (
            final_pass.get("status") == "comparable"
            and historical.get("final_pass") == current.get("final_pass")
        ),
    }
    human_review_waived = skip_human_review is True
    if human_review_waived:
        blocking_reasons = [
            name
            for name, passed in checks.items()
            if not passed and name != "human_review_complete"
        ]
    else:
        blocking_reasons = [name for name, passed in checks.items() if not passed]
    automated_checks_pass = not blocking_reasons
    return {
        "schema_version": "layered-evaluation-evidence-audit-v1",
        "status": "complete" if automated_checks_pass else "incomplete",
        "release_gate": automated_checks_pass and not human_review_waived,
        "automated_gate": automated_checks_pass,
        "human_review_policy": {
            "status": "waived" if human_review_waived else (
                "complete" if human_review_complete else "required"
            ),
            "evidence_collected": human_review_complete,
            "waiver_reason": waiver_reason if human_review_waived else None,
        },
        "checks": checks,
        "blocking_reasons": blocking_reasons,
        "requirements": {
            "minimum_reviewed": minimum_reviewed,
            "expected_cases": expected_cases,
            "expected_attempts": expected_attempts,
        },
    }


def _baseline_size(
    report: Mapping[str, Any], *, expected_cases: int, expected_attempts: int
) -> bool:
    return (
        report.get("selected_cases") == expected_cases
        and report.get("completed_cases") == expected_cases
        and report.get("attempts") == expected_attempts
    )


def _integer_at_least(value: Any, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _equal_positive_ints(value: Mapping[str, Any], names: tuple[str, ...]) -> bool:
    values = [value.get(name) for name in names]
    return bool(values) and all(
        isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in values
    ) and len(set(values)) == 1


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = ["audit_layered_evidence"]
