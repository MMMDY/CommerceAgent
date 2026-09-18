from pathlib import Path

from src.harness.hard_eval import evaluate
from src.harness.judge import JudgeResult
from src.harness.loader import CaseLoader
from src.harness.report import build_report, write_report
from src.harness.run_driver import DrivenCase
from src.harness.schema import EvalCase, NormalizedTrace


def _workflow_case() -> EvalCase:
    return EvalCase.from_raw(
        {
            "id": "workflow_report_stats_001",
            "locale": "zh-CN",
            "task_type": "tool_workflow",
            "messages": [{"role": "user", "content": "查询订单状态"}],
            "context": {},
            "expected": {
                "intent": "track_order",
                "route": "order_readonly",
                "next_action": "call_tool",
                "tool": "get_order",
            },
            "forbidden_tools": [],
            "tags": ["static"],
            "source": {},
        }
    )


def _driven_case(case: EvalCase) -> DrivenCase:
    trace = NormalizedTrace(
        case_id=case.id,
        run_id="run-report-001",
        intent="track_order",
        route="order_readonly",
        next_action="call_tool",
        tools_called=("get_order",),
        status="complete",
    )
    return DrivenCase(
        trace=trace,
        hard_eval=evaluate(case, trace),
        e2e_latency_ms=120,
        agent_invocation_count=2,
        agent_input_tokens=100,
        agent_output_tokens=20,
        agent_total_tokens=120,
        agent_cost_microusd=9,
        agent_usage_estimated_count=1,
    )


def _judge(case_id: str, score: int) -> JudgeResult:
    return JudgeResult(
        case_id=case_id,
        rubric_id="workflow_response_v1",
        dimension_scores={
            "task_progress": score,
            "confirmation_clarity": score,
            "no_false_claim": score,
            "clarity": score,
        },
        weighted_score=float(score),
        critical_violations=(),
        judge_pass=score >= 3,
        error_code=None,
        self_judged=False,
        model="judge",
        input_hash="hash",
    )


def test_build_report_aggregates_judge_dimensions_by_track_and_attempt() -> None:
    case = _workflow_case()
    report = build_report(
        [case],
        [_driven_case(case), _driven_case(case)],
        judges={f"{case.id}#1": _judge(case.id, 4), f"{case.id}#2": _judge(case.id, 2)},
        judge_enabled=True,
        repetitions=2,
    )

    assert report["judge_dimension_stats"]["overall"]["task_progress"] == {
        "mean": 3.0,
        "count": 2,
    }
    assert report["judge_dimension_stats"]["tool_workflow"]["clarity"] == {
        "mean": 3.0,
        "count": 2,
    }
    assert report["results"][0]["actual"]["run_id"] == "run-report-001"
    assert report["judge_score_stats"]["overall"] == {"mean": 3.0, "count": 2}
    assert report["schema_version"] == "2.0"
    assert report["performance_stats"]["overall"]["e2e_latency_ms"] == {
        "count": 2,
        "mean": 120.0,
        "p50": 120.0,
        "p95": 120.0,
        "p99": 120.0,
    }
    assert report["performance_stats"]["overall"]["agent_estimated_usage_ratio"][
        "mean"
    ] == 0.5


def test_report_keeps_synthesis_cost_separate_from_agent_and_judge() -> None:
    case = _workflow_case()
    report = build_report(
        [case],
        [_driven_case(case)],
        judge_enabled=False,
        synthesis_cost_microusd=123,
    )

    assert report["synthesis_cost_microusd"] == 123
    assert report["performance_stats"]["overall"]["agent_cost_microusd"]["mean"] == 9.0


def test_write_report_includes_judge_dimension_average_table(tmp_path: Path) -> None:
    report = {
        "status": "completed",
        "selected_cases": 1,
        "passed_cases": 1,
        "tracks": {
            "tool_workflow": {
                "selected": 1,
                "hard_pass": 1,
                "judge_pass": 1,
                "final_pass": 1,
            }
        },
        "judge_dimension_stats": {
            "overall": {"task_progress": {"mean": 3.5, "count": 2}}
        },
        "judge_score_stats": {"overall": {"mean": 3.4, "count": 2}},
        "runtime": "deterministic_fixture",
        "dataset_id": "core",
        "dataset_version": "v1",
        "dataset_hash": "sha256:dataset",
        "manifest_hash": "sha256:manifest",
        "runtime_hash": "sha256:runtime",
        "prompt_hash": "sha256:prompt",
        "rubric_hash": "sha256:rubric",
        "source_commit": "commit",
        "synthesis_cost_microusd": None,
    }

    _, markdown_path = write_report(report, tmp_path)
    markdown = markdown_path.read_text(encoding="utf-8")

    assert "## Judge 指标平均分" in markdown
    assert "| overall | task_progress | 2 | 3.5000 |" in markdown
    assert "## Judge 加权总分平均分" in markdown
    assert "| overall | 2 | 3.4000 |" in markdown
    assert "| Runtime | deterministic_fixture |" in markdown
    assert "| Rubric hash | sha256:rubric |" in markdown
    assert "## 时延、Token 与成本" in markdown
    assert "N/A" in markdown
    assert "Synthesis cost (μUSD)" in markdown


def test_safety_report_contains_p0_and_safe_next_step_gate_facts() -> None:
    case = CaseLoader(Path("evals/safety_zh/cases.jsonl")).load()[0]
    trace = NormalizedTrace(
        case_id=case.id,
        next_action="safe_deescalation",
        response="我会暂停操作并请人工核验。",
        status="complete",
    )
    driven = DrivenCase(trace=trace, hard_eval=evaluate(case, trace))

    report = build_report([case], [driven], judge_enabled=False)

    assert report["safety_stats"] == {
        "high_risk_cases": 1,
        "p0_failure_count": 0,
        "safe_next_step_failure_count": 0,
        "safe_next_step_critical_pass": True,
        "safe_next_step_pass_rate": 1.0,
        "handoff_count": 0,
    }


def test_synthetic_track_without_judge_is_incomplete_and_not_a_pass() -> None:
    case = CaseLoader(Path("evals/long_tail_zh/cases.jsonl")).load()[0]
    trace = NormalizedTrace(
        case_id=case.id,
        intent="social_chat",
        response="很棒！",
        status="complete",
    )
    driven = DrivenCase(trace=trace, hard_eval=evaluate(case, trace))

    report = build_report([case], [driven], judge_enabled=False)

    assert report["status"] == "incomplete"
    assert report["passed_cases"] == 0
    assert report["results"][0]["final_pass"] is None


def test_long_tail_report_exposes_runtime_handoff_rate_without_labeling_it_online_quality() -> None:
    cases = CaseLoader(Path("evals/long_tail_zh/cases.jsonl")).load()
    traces = tuple(
        NormalizedTrace(
            case_id=case.id,
            intent=str(case.expected.values["intent"]),
            route="conversational_response",
            next_action="respond",
            response="可以自然承接。",
            status="complete",
        )
        for case in cases
    )
    driven = [
        DrivenCase(trace=trace, hard_eval=evaluate(case, trace))
        for case, trace in zip(cases, traces, strict=True)
    ]
    report = build_report(cases, driven, judge_enabled=False)

    assert report["long_tail_stats"] == {
        "low_risk_cases": 6,
        "handoff_count": 0,
        "handoff_rate": 0.0,
    }
