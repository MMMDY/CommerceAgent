import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.api import main
from apps.api.main import create_app
from src.harness.multiturn_dashboard import build_multiturn_review_status, build_multiturn_trace


def _report() -> dict[str, object]:
    return {
        "schema_version": "multiturn-report-v1",
        "dataset_id": "pilot",
        "dataset_version": "pilot-v1",
        "runtime": "deterministic_pilot_agent",
        "status": "completed",
        "release_gate": False,
        "gate_status": "candidate_only",
        "scenario_count": 1,
        "dialogue_count": 1,
        "completed_count": 1,
        "incomplete_count": 0,
        "evaluation_noise_count": 0,
        "intent_coverage": {"mean": 1.0, "denominator": 1},
        "task_success_rate": {"mean": 1.0, "denominator": 1},
        "reference_solution": "hidden gold response",
        "simulator_config": {"prompt": "internal prompt"},
        "reports": [
            {
                "scenario_id": "pilot_order_001_v1",
                "dialogue_id": "dialogue-001",
                "status": "completed",
                "termination_reason": "all_key_intents_addressed",
                "intent_coverage": 1.0,
                "agenda_progress": 1.0,
                "exposed_intent_accuracy": 1.0,
                "task_success": True,
                "evaluation_noise": False,
                "metadata": {
                    "key_intents": ["查询物流状态"],
                    "prompt": "hidden metadata prompt",
                    "reference_solution": "hidden metadata gold",
                },
                "feedback": [],
                "turns": [
                    {
                        "scenario_id": "pilot_order_001_v1",
                        "dialogue_id": "dialogue-001",
                        "turn_id": 1,
                        "user_action": {
                            "action": "initial_request",
                            "message": "订单 13800138000 的物流到哪了？",
                            "target_intents": ["查询物流状态"],
                            "revealed_facts": [],
                            "emotion": "neutral",
                            "should_continue": True,
                            "reason_code": "initial_request",
                        },
                        "agent_trace": {
                            "route": "order_delivery",
                            "intent": "查询物流状态",
                            "next_action": "respond",
                            "tools_called": ["delivery_tracking"],
                            "evidence_ids": ["tool_observed:delivery_tracking"],
                            "response": "包裹正在运输中。",
                            "status": "complete",
                            "args": {"order_id": "hidden-order-id"},
                            "slot_values": {"phone": "13800138000"},
                        },
                        "raised_intents": ["查询物流状态"],
                        "addressed_intents": ["查询物流状态"],
                        "intent_states": {"查询物流状态": "ADDRESSED"},
                        "transitions": [],
                        "verifier_pass": True,
                        "version_hash": "sha256:" + "a" * 64,
                    }
                ],
            }
        ],
    }


def test_multiturn_projection_excludes_gold_prompt_and_runtime_payload() -> None:
    result = build_multiturn_trace(_report(), report_id="pilot", scenario_id="pilot_order_001_v1")
    encoded = json.dumps(result, ensure_ascii=False)

    assert "reference_solution" not in encoded
    assert "hidden gold" not in encoded
    assert "internal prompt" not in encoded
    assert "hidden metadata prompt" not in encoded
    assert "hidden-order-id" not in encoded
    assert "slot_values" not in encoded
    assert "[PHONE_REDACTED]" in encoded
    assert result["turns"][0]["agent_trace"]["response"] == "包裹正在运输中。"


def test_multiturn_report_api_lists_and_projects_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "pilot"
    report_dir.mkdir()
    (report_dir / "multiturn-report.json").write_text(
        json.dumps(_report(), ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(main, "MULTITURN_REPORT_ROOT", tmp_path)

    client = TestClient(create_app())
    listed = client.get("/v1/multiturn-reports")
    assert listed.status_code == 200
    assert listed.json()[0]["report_id"] == "pilot"

    dashboard = client.get("/v1/multiturn-reports/pilot/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["dialogues"][0]["scenario_id"] == "pilot_order_001_v1"
    assert dashboard.json()["human_review"]["status"] == "incomplete"
    assert dashboard.json()["human_review"]["reviewed_count"] == 0

    trace = client.get("/v1/multiturn-reports/pilot/traces/pilot_order_001_v1")
    assert trace.status_code == 200
    assert "reference_solution" not in trace.text
    assert "hidden-order-id" not in trace.text
    assert "pilot_order_001_v1" in trace.text

    detail = client.get("/v1/multiturn-reports/pilot")
    assert detail.status_code == 200
    assert "turns" not in detail.text


def test_multiturn_api_projects_review_sidecar_without_source_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "pilot"
    report_dir.mkdir()
    (report_dir / "multiturn-report.json").write_text(
        json.dumps(_report(), ensure_ascii=False), encoding="utf-8"
    )
    (report_dir / "human-review-stats.json").write_text(
        json.dumps(
            {
                "source_labels": "/private/labels.jsonl",
                "stats": {
                    "status": "complete",
                    "selected_count": 20,
                    "reviewed_count": 20,
                    "minimum_count": 20,
                    "gate_pass": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "MULTITURN_REPORT_ROOT", tmp_path)

    response = TestClient(create_app()).get("/v1/multiturn-reports/pilot/dashboard")

    assert response.status_code == 200
    assert response.json()["human_review"] == {
        "status": "complete",
        "selected_count": 20,
        "reviewed_count": 20,
        "minimum_count": 20,
        "gate_pass": True,
    }
    assert "/private/labels.jsonl" not in response.text


def test_review_status_projection_is_fail_closed_and_allowlisted() -> None:
    result = build_multiturn_review_status(
        {
            "stats": {"status": "incomplete", "reviewed_count": 0},
            "source_labels": "/private/labels.jsonl",
        }
    )

    assert result == {"status": "incomplete", "reviewed_count": 0}


@pytest.mark.parametrize("report_id", ["../pilot", "/tmp/pilot", "a/../../b", ""])
def test_multiturn_report_path_rejects_invalid_ids(report_id: str) -> None:
    with pytest.raises(HTTPException) as error:
        main._multiturn_report_path(report_id)
    assert error.value.status_code == 404


def test_multiturn_report_api_returns_not_found_for_missing_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(main, "MULTITURN_REPORT_ROOT", tmp_path)
    response = TestClient(create_app()).get("/v1/multiturn-reports/missing/dashboard")
    assert response.status_code == 404
