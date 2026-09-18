"""Versioned, browser-safe evaluation dashboard DTOs.

The report generator is the source of truth for release gates.  This module
only projects that report into a stable presentation contract; it deliberately
does not expose case prompts, expected text, model rationale, or raw traces.
"""

from __future__ import annotations

from typing import Any


def build_eval_dashboard(report: dict[str, Any]) -> dict[str, Any]:
    """Build a conservative dashboard projection from a persisted report.

    Missing values stay ``None``/``unknown``.  The UI must never infer a pass
    from an empty list or a missing Judge result.
    """

    tracks = _safe_mapping(report.get("tracks"))
    performance = _safe_mapping(report.get("performance_stats"))
    dimensions = _safe_mapping(report.get("judge_dimension_stats"))
    score_stats = _safe_mapping(report.get("judge_score_stats"))
    selected = _non_negative_int(report.get("selected_cases"))
    completed = _non_negative_int(report.get("completed_cases"))
    passed = _non_negative_int(report.get("passed_cases"))
    failed = _non_negative_int(report.get("failed_cases"))

    hard_pass = _track_sum(tracks, "hard_pass")
    judge_pass = _track_sum(tracks, "judge_pass")
    final_pass = passed if passed is not None else None
    funnel = [
        _funnel_stage("selected", "选入数据集", selected),
        _funnel_stage("completed", "已完成", completed),
        _funnel_stage("hard_gate", "Hard Gate", hard_pass),
        _funnel_stage("judge", "LLM Judge", judge_pass),
        _funnel_stage("final", "Final Pass", final_pass),
    ]

    gate = _gate_projection(report, selected=selected, completed=completed, failed=failed)
    human_approval = report.get("human_approval")
    approval = {
        "required": human_approval.get("required") is True,
        "status": _string_or_unknown(human_approval.get("status")),
        "source": _string_or_unknown(human_approval.get("source")),
    } if isinstance(human_approval, dict) else {
        "required": False,
        "status": "not_required",
        "source": "N/A",
    }
    return {
        "schema_version": "1.0",
        "dto": "evaluation_dashboard",
        "eval_run_id": _string_or_none(report.get("eval_run_id")),
        "status": _string_or_unknown(report.get("status")),
        "runtime": _string_or_unknown(report.get("runtime")),
        "mode": _string_or_unknown(report.get("mode")),
        "judge": _string_or_unknown(report.get("judge")),
        "self_judged": (
            report.get("self_judged") if isinstance(report.get("self_judged"), bool) else None
        ),
        "provisional": (
            report.get("provisional") if isinstance(report.get("provisional"), bool) else None
        ),
        "dataset": {
            "id": _string_or_none(report.get("dataset_id")),
            "version": _string_or_none(report.get("dataset_version")),
            "hash": _string_or_none(report.get("dataset_hash")),
        },
        "runtime_hash": _string_or_none(report.get("runtime_hash")),
        "manifest_hash": _string_or_none(report.get("manifest_hash")),
        "counts": {
            "selected": selected,
            "completed": completed,
            "passed": passed,
            "failed": failed,
            "attempts": _non_negative_int(report.get("attempts")),
            "repetitions": _positive_int(report.get("repetitions"), default=1),
        },
        "rates": {
            "first_pass": _bounded_rate(report.get("first_pass_rate")),
            "all_repetitions_pass": _bounded_rate(report.get("all_repetitions_pass_rate")),
        },
        "gate": gate,
        "human_approval": approval,
        "funnel": funnel,
        "tracks": tracks,
        "judge_dimensions": dimensions,
        "judge_scores": score_stats,
        "performance": performance,
        "safety": _safe_mapping(report.get("safety_stats")),
        "limitations": _limitations(report),
    }


def build_eval_case_detail(row: dict[str, Any], *, attempt_no: int) -> dict[str, Any]:
    """Project one report row into a browser-safe Case → Trace DTO.

    Evaluation reports may contain more fields than the UI is allowed to see.
    Keep this projection deliberately allowlisted: no prompt, expected outcome,
    raw response, tool arguments, or hidden model reasoning crosses the API.
    """

    actual = _safe_mapping(row.get("actual"))
    tools = _safe_string_list(actual.get("tools_called"), limit=16)
    evidence_ids = _safe_string_list(actual.get("evidence_ids"), limit=32)
    judge_evidence = _safe_string_list(row.get("judge_evidence"), limit=8, item_limit=160)
    judge_summary = row.get("judge_summary")
    return {
        "case_id": _string_or_none(row.get("case_id")),
        "track": _string_or_unknown(row.get("track")),
        "attempt_no": attempt_no if attempt_no > 0 else 1,
        "hard": {
            "passed": row.get("hard_pass") if isinstance(row.get("hard_pass"), bool) else None,
            "fail_reasons": _safe_string_list(row.get("hard_fail_reasons"), limit=16),
        },
        "judge": {
            "passed": row.get("judge_pass") if isinstance(row.get("judge_pass"), bool) else None,
            "score": (
                row.get("judge_score")
                if isinstance(row.get("judge_score"), int | float)
                and not isinstance(row.get("judge_score"), bool)
                else None
            ),
            "dimensions": _safe_scores(row.get("judge_dimensions")),
            "error": _string_or_none(row.get("judge_error")),
            "summary": (
                judge_summary[:120]
                if isinstance(judge_summary, str) and judge_summary
                else None
            ),
            "evidence": judge_evidence,
        },
        "final_pass": row.get("final_pass") if isinstance(row.get("final_pass"), bool) else None,
        "runtime_error": _string_or_none(row.get("runtime_error")),
        "trace": {
            "run_id": _string_or_none(actual.get("run_id")),
            "route": _string_or_none(actual.get("route")),
            "intent": _string_or_none(actual.get("intent")),
            "next_action": _string_or_none(actual.get("next_action")),
            "tools_called": tools,
            "evidence_ids": evidence_ids,
            "status": _string_or_unknown(actual.get("status")),
            "response_present": (
                actual.get("response_present")
                if isinstance(actual.get("response_present"), bool)
                else None
            ),
        },
        "flow": _case_flow(row, actual),
    }


def _case_flow(row: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, str]]:
    hard = row.get("hard_pass") if isinstance(row.get("hard_pass"), bool) else None
    judge = row.get("judge_pass") if isinstance(row.get("judge_pass"), bool) else None
    final = row.get("final_pass") if isinstance(row.get("final_pass"), bool) else None
    route = _string_or_none(actual.get("route"))
    intent = _string_or_none(actual.get("intent"))
    tools = _safe_string_list(actual.get("tools_called"), limit=16)
    evidence = _safe_string_list(actual.get("evidence_ids"), limit=32)
    return [
        {
            "id": "hard",
            "label": "Hard Gate",
            "status": _flow_status(hard),
            "detail": _flow_detail(hard, "规则断言"),
        },
        {
            "id": "route",
            "label": "路由 / 意图",
            "status": "done" if route or intent else "na",
            "detail": " · ".join(item for item in (route, intent) if item) or "N/A",
        },
        {
            "id": "execution",
            "label": "Agent 执行",
            "status": "done" if tools or actual.get("response_present") else "warning",
            "detail": f"工具 {len(tools)} 次 · RAG 证据 {len(evidence)} 条",
        },
        {
            "id": "judge",
            "label": "LLM Judge",
            "status": _flow_status(judge),
            "detail": _flow_detail(judge, "Rubric 评分"),
        },
        {
            "id": "final",
            "label": "Final Pass",
            "status": _flow_status(final),
            "detail": _flow_detail(final, "发布判定"),
        },
    ]


def _flow_status(value: bool | None) -> str:
    return "done" if value is True else "failed" if value is False else "na"


def _flow_detail(value: bool | None, label: str) -> str:
    if value is True:
        return f"{label}：通过"
    if value is False:
        return f"{label}：失败"
    return f"{label}：N/A"


def _gate_projection(
    report: dict[str, Any], *, selected: int | None, completed: int | None, failed: int | None
) -> dict[str, Any]:
    reasons: list[str] = []
    status = _string_or_unknown(report.get("status"))
    judge = report.get("judge")
    self_judged = report.get("self_judged")
    release_gate = report.get("release_gate")
    if status != "completed":
        reasons.append("report_not_completed")
    if selected is None or completed is None or selected != completed:
        reasons.append("case_completion_incomplete")
    if failed is not None and failed > 0:
        reasons.append("failed_cases_present")
    if judge != "on":
        reasons.append("judge_not_enabled")
    if self_judged is not False:
        reasons.append("judge_independence_unverified")
    if release_gate is not True:
        reasons.append("release_gate_not_passed")
    return {
        "release_gate": release_gate if isinstance(release_gate, bool) else None,
        "hard_gate": (
            "pass" if not reasons and failed == 0 else ("fail" if failed else "incomplete")
        ),
        "status": (
            "pass"
            if not reasons
            else ("fail" if "failed_cases_present" in reasons else "incomplete")
        ),
        "reasons": reasons,
    }


def _track_sum(tracks: dict[str, Any], key: str) -> int | None:
    if not tracks:
        return None
    total = 0
    for value in tracks.values():
        if not isinstance(value, dict) or not isinstance(value.get(key), int):
            return None
        item = value[key]
        if item < 0:
            return None
        total += item
    return total


def _funnel_stage(stage_id: str, label: str, count: int | None) -> dict[str, Any]:
    return {"id": stage_id, "label": label, "count": count, "available": count is not None}


def _limitations(report: dict[str, Any]) -> list[str]:
    limitations: list[str] = []
    if report.get("runtime") == "deterministic_fixture":
        limitations.append("deterministic_fixture_not_live_model_evidence")
    if report.get("self_judged") is True:
        limitations.append("self_judged_is_provisional")
    if report.get("judge") != "on":
        limitations.append("judge_metrics_unavailable")
    return limitations


def _safe_mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_string_list(value: object, *, limit: int, item_limit: int = 128) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [item[:item_limit] for item in value[:limit] if isinstance(item, str) and item]


def _safe_scores(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key)[:64]: int(item)
        for key, item in value.items()
        if (
            isinstance(key, str)
            and isinstance(item, int)
            and not isinstance(item, bool)
            and 0 <= item <= 4
        )
    }


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_or_unknown(value: object) -> str:
    return value if isinstance(value, str) and value else "unknown"


def _non_negative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _positive_int(value: object, *, default: int) -> int:
    return (
        value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default
    )


def _bounded_rate(value: object) -> float | None:
    return (
        value
        if isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 1
        else None
    )


__all__ = ["build_eval_case_detail", "build_eval_dashboard"]
