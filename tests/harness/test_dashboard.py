from src.harness.dashboard import build_eval_case_detail, build_eval_dashboard


def test_dashboard_projects_gate_and_funnel_without_case_text() -> None:
    result = build_eval_dashboard(
        {
            "eval_run_id": "eval-1",
            "status": "completed",
            "runtime": "deterministic_fixture",
            "mode": "release",
            "judge": "on",
            "self_judged": False,
            "release_gate": True,
            "selected_cases": 2,
            "completed_cases": 2,
            "passed_cases": 1,
            "failed_cases": 1,
            "tracks": {"core": {"selected": 2, "hard_pass": 1, "judge_pass": 1, "final_pass": 1}},
            "results": [{"prompt": "must not be projected"}],
        }
    )

    assert result["gate"]["status"] == "fail"
    assert result["funnel"][2]["count"] == 1
    assert result["funnel"][4]["count"] == 1
    assert "results" not in result
    assert "limitations" in result


def test_dashboard_keeps_missing_aggregates_unknown() -> None:
    result = build_eval_dashboard({"status": "incomplete", "judge": "off"})

    assert result["funnel"][2]["count"] is None
    assert result["gate"]["release_gate"] is None
    assert result["gate"]["status"] == "incomplete"
    assert result["human_approval"] == {
        "required": False,
        "status": "not_required",
        "source": "N/A",
    }


def test_dashboard_projects_pending_human_approval_without_granting_release() -> None:
    result = build_eval_dashboard(
        {
            "status": "incomplete",
            "judge": "on",
            "release_gate": False,
            "human_approval": {
                "required": True,
                "status": "pending",
                "source": "separate_approver_workflow",
            },
        }
    )

    assert result["human_approval"] == {
        "required": True,
        "status": "pending",
        "source": "separate_approver_workflow",
    }
    assert result["gate"]["release_gate"] is False


def test_dashboard_projects_server_aggregated_rubric_dimensions() -> None:
    result = build_eval_dashboard(
        {
            "status": "completed",
            "judge": "on",
            "judge_dimension_stats": {
                "overall": {"clarity": {"mean": 3.5, "count": 4}},
                "long_tail_response_v1": {"clarity": {"mean": 3.0, "count": 2}},
            },
        }
    )

    assert result["judge_dimensions"]["overall"]["clarity"] == {"mean": 3.5, "count": 4}
    assert result["judge_dimensions"]["long_tail_response_v1"]["clarity"]["mean"] == 3.0


def test_case_detail_is_allowlisted_and_exposes_trace_flow() -> None:
    result = build_eval_case_detail(
        {
            "case_id": "case_001",
            "track": "tool_workflow",
            "hard_pass": False,
            "hard_fail_reasons": ["route_mismatch"],
            "judge_pass": True,
            "judge_score": 3.5,
            "judge_dimensions": {"clarity": 4, "unsafe": 9},
            "judge_summary": "完成了主要任务",
            "judge_evidence": ["evidence:1"],
            "final_pass": False,
            "actual": {
                "run_id": "run-001",
                "route": "order_readonly",
                "intent": "track_order",
                "next_action": "call_tool",
                "tools_called": ["get_order"],
                "evidence_ids": ["knowledge:1"],
                "status": "complete",
                "response_present": True,
                "args": {"order_id": "must not be projected"},
            },
        },
        attempt_no=1,
    )

    assert result["trace"]["route"] == "order_readonly"
    assert result["trace"]["run_id"] == "run-001"
    assert result["trace"]["tools_called"] == ["get_order"]
    assert result["judge"]["dimensions"] == {"clarity": 4}
    assert result["flow"][-1]["status"] == "failed"
    assert "args" not in result
    assert "must not be projected" not in str(result)
