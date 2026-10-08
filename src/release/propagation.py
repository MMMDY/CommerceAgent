"""Fail-closed evaluation of rollback and kill-switch propagation evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

PropagationStatus = Literal["pass", "fail", "incomplete"]


@dataclass(frozen=True, slots=True)
class PropagationEvidence:
    action: str
    control_changed_at: datetime
    first_post_change_request_at: datetime | None
    forbidden_matches_after_change: int
    historical_run_reference_preserved: bool | None = None


@dataclass(frozen=True, slots=True)
class PropagationResult:
    action: str
    status: PropagationStatus
    elapsed_seconds: float | None
    reason: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_propagation(
    evidence: PropagationEvidence, *, deadline_seconds: float = 60.0
) -> PropagationResult:
    """Evaluate the first real request observed after a control-plane change.

    ``incomplete`` is returned when no post-change request was observed.  A
    missing observation is never interpreted as successful propagation.
    """

    if not evidence.action.strip():
        raise ValueError("action_required")
    if deadline_seconds <= 0:
        raise ValueError("deadline_seconds_must_be_positive")
    if evidence.control_changed_at.tzinfo is None:
        raise ValueError("control_changed_at_must_be_timezone_aware")
    is_rollback = "rollback" in evidence.action.lower()
    if is_rollback and evidence.historical_run_reference_preserved is False:
        return PropagationResult(
            action=evidence.action,
            status="fail",
            elapsed_seconds=None,
            reason="historical_run_reference_not_preserved",
        )
    if is_rollback and evidence.historical_run_reference_preserved is not True:
        return PropagationResult(
            action=evidence.action,
            status="incomplete",
            elapsed_seconds=None,
            reason="historical_run_reference_observation_missing",
        )
    if evidence.first_post_change_request_at is not None:
        if evidence.first_post_change_request_at.tzinfo is None:
            raise ValueError("first_post_change_request_at_must_be_timezone_aware")
        elapsed = (
            evidence.first_post_change_request_at - evidence.control_changed_at
        ).total_seconds()
        if elapsed < 0:
            return PropagationResult(
                action=evidence.action,
                status="fail",
                elapsed_seconds=round(elapsed, 3),
                reason="first_request_precedes_control_change",
            )
        if evidence.forbidden_matches_after_change > 0:
            return PropagationResult(
                action=evidence.action,
                status="fail",
                elapsed_seconds=round(elapsed, 3),
                reason="new_request_matched_disabled_control",
            )
        if elapsed > deadline_seconds:
            return PropagationResult(
                action=evidence.action,
                status="fail",
                elapsed_seconds=round(elapsed, 3),
                reason="propagation_exceeded_deadline",
            )
        return PropagationResult(
            action=evidence.action,
            status="pass",
            elapsed_seconds=round(elapsed, 3),
            reason="propagation_within_deadline",
        )
    if evidence.forbidden_matches_after_change > 0:
        return PropagationResult(
            action=evidence.action,
            status="fail",
            elapsed_seconds=None,
            reason="forbidden_match_without_first_request_timestamp",
        )
    return PropagationResult(
        action=evidence.action,
        status="incomplete",
        elapsed_seconds=None,
        reason="no_post_change_request_observed",
    )


__all__ = [
    "PropagationEvidence",
    "PropagationResult",
    "PropagationStatus",
    "evaluate_propagation",
]
