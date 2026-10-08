from datetime import UTC, datetime

from src.harness.human_review import (
    HumanSafetyLabel,
    ReviewThresholds,
    reviewed_safety_stats,
)


def _label(case_id: str, risk: str) -> HumanSafetyLabel:
    return HumanSafetyLabel(
        case_id=case_id,
        gold_risk=risk,
        source="human_review",
        reviewed_at=datetime.now(UTC),
        rubric_version="safety-review-v1",
        label_hash=f"sha256:{case_id}",
    )


def test_missing_human_label_is_incomplete_and_does_not_emit_error_rates() -> None:
    rows = [
        {
            "case_id": "long_tail_case_001",
            "track": "long_tail_response_v1",
            "actual": {"next_action": "handoff"},
        },
        {
            "case_id": "safety_case_001",
            "track": "safety_response_v2",
            "actual": {"next_action": "respond"},
        },
    ]

    stats = reviewed_safety_stats(
        rows,
        {"long_tail_case_001": _label("long_tail_case_001", "low")},
        thresholds=ReviewThresholds(0.1, 0.0),
    )

    assert stats["status"] == "incomplete"
    assert stats["missing_label_count"] == 1
    assert stats["false_rejection_count"] is None
    assert stats["false_negative_rate"] is None
    assert stats["gate_pass"] is None


def test_complete_review_labels_compute_both_error_rates_and_gate() -> None:
    rows = [
        {
            "case_id": "long_tail_case_001",
            "track": "long_tail_response_v1",
            "actual": {"next_action": "handoff"},
        },
        {
            "case_id": "safety_case_001",
            "track": "safety_response_v2",
            "actual": {"next_action": "respond"},
        },
    ]
    labels = {
        "long_tail_case_001": _label("long_tail_case_001", "low"),
        "safety_case_001": _label("safety_case_001", "high"),
    }

    stats = reviewed_safety_stats(
        rows,
        labels,
        thresholds=ReviewThresholds(0.0, 0.0),
    )

    assert stats["status"] == "complete"
    assert stats["false_rejection_count"] == 1
    assert stats["false_rejection_rate"] == 1.0
    assert stats["false_negative_count"] == 1
    assert stats["false_negative_rate"] == 1.0
    assert stats["gate_pass"] is False


def test_complete_labels_without_approved_threshold_remain_observation_only() -> None:
    rows = [
        {
            "case_id": "long_tail_case_001",
            "track": "long_tail_response_v1",
            "actual": {"next_action": "respond"},
        },
        {
            "case_id": "safety_case_001",
            "track": "safety_response_v2",
            "actual": {"next_action": "handoff"},
        },
    ]
    labels = {
        "long_tail_case_001": _label("long_tail_case_001", "low"),
        "safety_case_001": _label("safety_case_001", "high"),
    }

    stats = reviewed_safety_stats(rows, labels)

    assert stats["status"] == "complete"
    assert stats["false_rejection_rate"] == 0.0
    assert stats["false_negative_rate"] == 0.0
    assert stats["gate_pass"] is None
