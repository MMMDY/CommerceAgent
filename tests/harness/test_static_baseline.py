from scripts.compare_static_baseline import comparison_exit_code
from src.harness.layered_evidence import audit_layered_evidence
from src.harness.static_baseline import compare_static_baselines


def _report(*, judge: str, passed: int, rate: float, attempts: int = 900) -> dict:
    return {
        "status": "completed",
        "dataset_hash": "dataset",
        "selected_cases": 300,
        "completed_cases": 300,
        "repetitions": 3,
        "attempts": attempts,
        "hard_passed_cases": 300,
        "judge": judge,
        "passed_cases": passed,
        "all_repetitions_pass_rate": rate,
        "tracks": {
            "intent_route": {"selected": 150, "attempts": 450, "hard_pass": 150},
            "scripted_clarification": {"selected": 20, "attempts": 60, "hard_pass": 20},
            "tool_workflow": {"selected": 60, "attempts": 180, "hard_pass": 60},
            "rag_grounding": {"selected": 50, "attempts": 150, "hard_pass": 50},
            "guardrail_handoff": {"selected": 20, "attempts": 60, "hard_pass": 20},
        },
    }


def test_static_comparison_preserves_hard_invariants_and_isolates_judge_delta() -> None:
    result = compare_static_baselines(
        _report(judge="on", passed=296, rate=0.9867),
        _report(judge="off", passed=300, rate=1.0),
    )

    assert result["status"] == "invariant_preserved"
    assert result["evidence_status"] == "incomplete"
    assert result["comparison_scope"] == "hard_runtime_only"
    assert all(result["checks"].values())
    assert result["judge_dependent"]["status"] == "not_comparable"
    assert result["judge_dependent"]["signature_match"] is False
    assert result["judge_dependent"]["final_pass"]["status"] == "N/A"


def test_static_comparison_detects_attempt_shape_regression() -> None:
    result = compare_static_baselines(
        _report(judge="off", passed=300, rate=1.0),
        _report(judge="off", passed=300, rate=1.0, attempts=300),
    )

    assert result["status"] == "regression"
    assert result["checks"]["dataset_shape"] is False


def test_static_comparison_marks_incomplete_judge_as_not_comparable() -> None:
    historical = _report(judge="on", passed=296, rate=0.9867)
    current = _report(judge="on", passed=290, rate=0.9667)
    current["status"] = "incomplete"

    result = compare_static_baselines(historical, current)

    assert result["judge_dependent"]["final_pass"]["status"] == "N/A"
    assert result["evidence_status"] == "incomplete"
    assert result["report_status"]["both_completed"] is False
    assert result["judge_dependent"]["final_pass"]["reason"] == (
        "one or both reports are incomplete"
    )


def test_static_comparison_cli_fails_for_hard_only_evidence() -> None:
    result = compare_static_baselines(
        _report(judge="off", passed=300, rate=1.0),
        _report(judge="on", passed=300, rate=1.0),
    )

    assert result["status"] == "invariant_preserved"
    assert result["evidence_status"] == "incomplete"
    assert comparison_exit_code(result) == 1


def test_static_comparison_cli_passes_only_for_complete_evidence() -> None:
    historical = _report(judge="on", passed=300, rate=1.0)
    current = _report(judge="on", passed=300, rate=1.0)
    signature = {
        "mode": "on",
        "config_hash": "config",
        "models": [],
        "prompt_hash": "prompt",
        "rubric_hash": "rubric",
        "rubric_version": "1.0",
    }
    historical.update(
        {
            "judge_config_hash": signature["config_hash"],
            "judge_prompt_hash": signature["prompt_hash"],
            "rubric_hash": signature["rubric_hash"],
            "rubric_version": signature["rubric_version"],
        }
    )
    current.update(historical)
    historical["results"] = [{"case_id": "case", "judge_input_hash": "hash"}]
    current["results"] = [{"case_id": "case", "judge_input_hash": "hash"}]

    result = compare_static_baselines(historical, current)

    assert result["evidence_status"] == "complete"
    assert comparison_exit_code(result) == 0


def test_layered_evidence_audit_fails_closed_for_missing_human_review() -> None:
    comparison = compare_static_baselines(
        _report(judge="off", passed=300, rate=1.0),
        _report(judge="off", passed=300, rate=1.0),
    )

    result = audit_layered_evidence(
        {"stats": {"status": "incomplete", "reviewed_count": 0, "gate_pass": None}},
        comparison,
    )

    assert result["status"] == "incomplete"
    assert result["release_gate"] is False
    assert "human_review_complete" in result["blocking_reasons"]


def test_layered_evidence_audit_requires_same_judge_signature_and_final_pass() -> None:
    historical = _report(judge="on", passed=300, rate=1.0)
    current = _report(judge="on", passed=300, rate=1.0)
    for report in (historical, current):
        report.update(
            {
                "judge_config_hash": "config",
                "judge_prompt_hash": "prompt",
                "rubric_hash": "rubric",
                "rubric_version": "1.0",
                "results": [{"case_id": "case", "judge_input_hash": "hash"}],
            }
        )
    comparison = compare_static_baselines(historical, current)

    result = audit_layered_evidence(
        {"stats": {
            "status": "complete",
            "reviewed_count": 20,
            "selected_count": 20,
            "unique_selected_count": 20,
            "minimum_count": 20,
            "missing_label_count": 0,
            "extra_label_count": 0,
            "duplicate_scenario_ids": [],
            "gate_pass": True,
        }},
        comparison,
    )

    assert result["status"] == "complete"
    assert result["release_gate"] is True


def test_layered_evidence_audit_rejects_incomplete_hash_coverage_and_malformed_sections() -> None:
    result = audit_layered_evidence(
        {"stats": {
            "status": "complete",
            "reviewed_count": 20,
            "selected_count": 20,
            "unique_selected_count": 20,
            "minimum_count": 20,
            "missing_label_count": 0,
            "extra_label_count": 0,
            "duplicate_scenario_ids": [],
            "gate_pass": True,
        }},
        {
            "status": "invariant_preserved",
            "evidence_status": "complete",
            "comparison_scope": "hard_runtime_and_judge",
            "report_status": None,
            "checks": {
                "dataset_hash": True,
                "dataset_shape": True,
                "track_shape": True,
                "hard_pass": True,
            },
            "historical": {"selected_cases": 300, "completed_cases": 300, "attempts": 900},
            "current": {"selected_cases": 300, "completed_cases": 300, "attempts": 900},
            "judge_dependent": {
                "status": "comparable",
                "signature_match": True,
                "input_hashes": {
                    "status": "complete",
                    "historical_count": 450,
                    "current_count": 449,
                    "shared_count": 449,
                    "matching_count": 449,
                },
                "final_pass": {"status": "comparable"},
            },
        },
    )

    assert result["status"] == "incomplete"
    assert "judge_dependent_comparable" in result["blocking_reasons"]
    assert "baseline_reports_complete" in result["blocking_reasons"]
