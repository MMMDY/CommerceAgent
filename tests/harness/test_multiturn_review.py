import json
from datetime import UTC, datetime

import pytest

from src.harness.multiturn_review import (
    HumanTrajectoryReview,
    build_multiturn_review_queue,
    reviewed_multiturn_stats,
)


def test_review_queue_is_pending_and_excludes_hidden_evaluation_fields() -> None:
    report = {
        "dataset_id": "pilot",
        "dataset_version": "pilot-v1",
        "runtime": "deterministic_pilot_agent",
        "reports": [
            {
                "scenario_id": "pilot_case_001_v1",
                "dialogue_id": "dialogue-1",
                "reference_solution": {"answer": "hidden"},
                "metadata": {"key_intents": ["hidden intent"]},
                "turns": [
                    {
                        "turn_id": 1,
                        "raised_intents": ["hidden intent"],
                        "user_action": {
                            "message": "我想查物流",
                            "target_intents": ["hidden intent"],
                            "revealed_facts": ["hidden fact"],
                        },
                        "agent_trace": {
                            "response": "请提供订单号",
                            "route": "clarification",
                            "next_action": "ask_slot",
                            "tools_called": [],
                            "status": "complete",
                        },
                    }
                ],
            }
        ],
    }

    queue = build_multiturn_review_queue(report, sample_size=1)
    item = queue["items"][0]
    assert queue["status"] == "pending_human_review"
    assert item["turns"][0]["user_message"] == "我想查物流"
    assert item["turns"][0]["agent_response"] == "请提供订单号"
    assert item["review"]["simulator_action_validity"] is None
    assert "reference_solution" not in item
    assert "target_intents" not in item["turns"][0]
    assert "raised_intents" not in item["turns"][0]


def test_review_queue_samples_families_round_robin_and_prefers_multiturn_rows() -> None:
    def row(scenario_id: str, turns: int) -> dict:
        return {
            "scenario_id": scenario_id,
            "dialogue_id": f"dialogue-{scenario_id}",
            "turns": [
                {
                    "turn_id": turn_id,
                    "user_action": {"message": f"user {turn_id}"},
                    "agent_trace": {"response": f"agent {turn_id}"},
                }
                for turn_id in range(1, turns + 1)
            ],
        }

    queue = build_multiturn_review_queue(
        {"reports": [
            row("pilot_order_001_v1", 1),
            row("pilot_order_002_v1", 1),
            row("pilot_safety_003_v1", 1),
            row("pilot_compound_004_v1", 2),
        ]},
        sample_size=3,
    )

    assert [item["scenario_id"] for item in queue["items"]] == [
        "pilot_compound_004_v1",
        "pilot_order_001_v1",
        "pilot_safety_003_v1",
    ]
    assert queue["sampling"] == {
        "strategy": "stable_family_round_robin_v1",
        "candidate_count": 4,
    }


def test_review_queue_rejects_rows_without_projectable_turns() -> None:
    with pytest.raises(ValueError, match="fewer reviewable rows"):
        build_multiturn_review_queue(
            {"reports": [{
                "scenario_id": "pilot_case_001_v1",
                "turns": [{"turn_id": 1}],
            }]},
            sample_size=1,
        )


def _label(scenario_id: str, *, leakage: str = "none") -> HumanTrajectoryReview:
    return HumanTrajectoryReview(
        scenario_id=scenario_id,
        source="human_review",
        reviewer_id="reviewer-1",
        reviewed_at=datetime.now(UTC),
        rubric_version="multiturn-human-review-v1",
        gold_response_leakage=leakage,
        semantic_fidelity="pass",
        simulator_action_validity="pass",
        notes="human review note",
        label_hash=f"sha256:{scenario_id}",
    )


def test_missing_trajectory_labels_are_incomplete() -> None:
    stats = reviewed_multiturn_stats(
        [{"scenario_id": "pilot_case_001_v1"}],
        {"pilot_case_001_v1": _label("pilot_case_001_v1")},
        minimum_count=2,
    )

    assert stats["status"] == "incomplete"
    assert stats["gate_pass"] is None
    assert stats["unique_selected_count"] == 1


def test_complete_trajectory_labels_can_pass_only_without_leakage() -> None:
    rows = [{"scenario_id": "pilot_case_001_v1"}, {"scenario_id": "pilot_case_002_v1"}]
    labels = {
        row["scenario_id"]: _label(row["scenario_id"], leakage="none") for row in rows
    }

    stats = reviewed_multiturn_stats(rows, labels, minimum_count=2)

    assert stats["status"] == "complete"
    assert stats["gate_pass"] is True


def test_review_stats_reject_duplicate_or_extra_labels() -> None:
    rows = [{"scenario_id": "pilot_case_001_v1"}, {"scenario_id": "pilot_case_001_v1"}]
    labels = {
        "pilot_case_001_v1": _label("pilot_case_001_v1"),
        "pilot_case_002_v1": _label("pilot_case_002_v1"),
    }

    stats = reviewed_multiturn_stats(rows, labels, minimum_count=2)

    assert stats["status"] == "incomplete"
    assert stats["duplicate_scenario_ids"] == ["pilot_case_001_v1"]
    assert stats["extra_scenario_ids"] == ["pilot_case_002_v1"]


def test_review_label_requires_non_empty_notes() -> None:
    payload = _label("pilot_case_001_v1").model_dump(mode="json")
    payload["notes"] = ""

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HumanTrajectoryReview.model_validate(payload)


def test_review_label_loader_and_cli_input_contract(tmp_path) -> None:
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(
        json.dumps(_label("pilot_case_001_v1").model_dump(mode="json"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    from src.harness.multiturn_review import load_multiturn_review_labels

    loaded = load_multiturn_review_labels(labels_path)
    assert loaded["pilot_case_001_v1"].source == "human_review"
