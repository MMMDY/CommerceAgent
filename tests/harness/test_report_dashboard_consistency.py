"""Ensure browser and Markdown projections keep the report as one source of truth."""

from src.harness.dashboard import build_eval_dashboard
from src.harness.report import write_report


def test_dashboard_and_markdown_share_report_aggregates(tmp_path) -> None:
    report = {
        "eval_run_id": "eval-consistency-001",
        "status": "completed",
        "runtime": "synthetic",
        "mode": "release",
        "judge": "on",
        "selected_cases": 2,
        "completed_cases": 2,
        "passed_cases": 1,
        "failed_cases": 1,
        "attempts": 2,
        "repetitions": 1,
        "first_pass_rate": 0.5,
        "all_repetitions_pass_rate": 0.5,
        "release_gate": False,
        "tracks": {
            "long_tail_response_v1": {
                "selected": 2,
                "hard_pass": 1,
                "judge_pass": 1,
                "final_pass": 1,
            }
        },
        "judge_dimension_stats": {
            "overall": {"naturalness": {"count": 2, "mean": 3.25}}
        },
        "judge_score_stats": {"overall": {"count": 2, "mean": 3.5}},
        "performance_stats": {
            "overall": {
                "e2e_latency_ms": {
                    "count": 2,
                    "mean": 120.0,
                    "p50": 120.0,
                    "p95": 140.0,
                    "p99": 140.0,
                }
            }
        },
        "safety_stats": {
            "high_risk_cases": 1,
            "p0_failure_count": 0,
            "safe_next_step_failure_count": 0,
            "safe_next_step_pass_rate": 1.0,
            "safe_next_step_critical_pass": True,
        },
        "long_tail_stats": {"low_risk_cases": 2, "handoff_count": 0, "handoff_rate": 0.0},
    }

    dashboard = build_eval_dashboard(report)
    _, markdown_path = write_report(report, tmp_path)
    markdown = markdown_path.read_text(encoding="utf-8")

    assert dashboard["counts"] == {
        "selected": 2,
        "completed": 2,
        "passed": 1,
        "failed": 1,
        "attempts": 2,
        "repetitions": 1,
    }
    assert dashboard["rates"] == {"first_pass": 0.5, "all_repetitions_pass": 0.5}
    assert dashboard["tracks"] == report["tracks"]
    assert dashboard["judge_dimensions"] == report["judge_dimension_stats"]
    assert dashboard["judge_scores"] == report["judge_score_stats"]
    assert dashboard["performance"] == report["performance_stats"]
    assert dashboard["safety"] == report["safety_stats"]

    assert "| overall | naturalness | 2 | 3.2500 |" in markdown
    assert "| overall | 2 | 3.5000 |" in markdown
    assert (
        "| overall | e2e_latency_ms | 2 | 120.0000 | 120.0000 | "
        "140.0000 | 140.0000 |"
    ) in markdown
    assert "| 高危样本数 | 1 |" in markdown
