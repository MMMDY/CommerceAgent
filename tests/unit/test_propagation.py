from datetime import UTC, datetime, timedelta

import pytest

from src.release.propagation import PropagationEvidence, evaluate_propagation


def _evidence(**overrides: object) -> PropagationEvidence:
    changed = datetime(2026, 9, 18, 10, 0, tzinfo=UTC)
    values: dict[str, object] = {
        "action": "skill_kill_switch",
        "control_changed_at": changed,
        "first_post_change_request_at": changed + timedelta(seconds=12),
        "forbidden_matches_after_change": 0,
        "historical_run_reference_preserved": True,
    }
    values.update(overrides)
    return PropagationEvidence(**values)  # type: ignore[arg-type]


def test_propagation_passes_only_with_observed_safe_request_within_deadline() -> None:
    result = evaluate_propagation(_evidence())

    assert result.status == "pass"
    assert result.elapsed_seconds == 12.0


def test_propagation_fails_on_forbidden_match_or_deadline_breach() -> None:
    assert evaluate_propagation(
        _evidence(forbidden_matches_after_change=1)
    ).reason == "new_request_matched_disabled_control"
    assert evaluate_propagation(
        _evidence(first_post_change_request_at=datetime(2026, 9, 18, 10, 2, tzinfo=UTC))
    ).reason == "propagation_exceeded_deadline"


def test_missing_observation_is_incomplete_and_timestamps_are_validated() -> None:
    assert evaluate_propagation(
        _evidence(first_post_change_request_at=None)
    ).status == "incomplete"
    with pytest.raises(ValueError, match="timezone_aware"):
        evaluate_propagation(
            _evidence(control_changed_at=datetime(2026, 9, 18, 10, 0))
        )


def test_rollback_requires_historical_run_reference_evidence() -> None:
    assert evaluate_propagation(
        _evidence(action="skill_rollback", historical_run_reference_preserved=False)
    ).reason == "historical_run_reference_not_preserved"
    assert evaluate_propagation(
        _evidence(action="skill_rollback", historical_run_reference_preserved=None)
    ).reason == "historical_run_reference_observation_missing"
    assert evaluate_propagation(
        _evidence(action="skill_rollback", historical_run_reference_preserved=True)
    ).status == "pass"
