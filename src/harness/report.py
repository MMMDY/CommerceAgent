"""Deterministic aggregation and serialization of evaluation results."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.harness.judge import JudgeResult
from src.harness.run_driver import DrivenCase
from src.harness.schema import EvalCase
from src.telemetry.trace import _sanitize


@dataclass(frozen=True, slots=True)
class CaseReport:
    case_id: str
    track: str
    hard_pass: bool
    hard_fail_reasons: tuple[str, ...]
    dimensions: dict[str, bool]
    final_pass: bool | None
    judge_pass: bool | None
    judge_score: float | None
    judge_error: str | None
    self_judged: bool
    runtime_error: str | None
    e2e_latency_ms: int | None = None
    agent_invocation_count: int | None = None
    agent_input_tokens: int | None = None
    agent_output_tokens: int | None = None
    agent_total_tokens: int | None = None
    agent_cost_microusd: int | None = None
    agent_usage_estimated_count: int | None = None
    judge_latency_ms: int | None = None
    judge_total_tokens: int | None = None
    judge_cost_microusd: int | None = None
    judge_dimensions: dict[str, int] | None = None
    critical_violations: tuple[str, ...] = ()
    judge_input_hash: str | None = None
    judge_model: str | None = None
    judge_summary: str | None = None
    judge_evidence: tuple[str, ...] = ()
    expected: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None


def build_report(
    cases: Iterable[EvalCase],
    results: Iterable[DrivenCase],
    *,
    judges: dict[str, JudgeResult] | None = None,
    dataset_hash: str | None = None,
    dataset_id: str | None = None,
    dataset_version: str | None = None,
    manifest_hash: str | None = None,
    runtime_hash: str | None = None,
    runtime: str | None = None,
    prompt_hash: str | None = None,
    rubric_hash: str | None = None,
    runtime_versions: dict[str, Any] | None = None,
    synthesis_cost_microusd: int | None = None,
    mode: str = "debug",
    repetitions: int = 1,
    cancelled: bool = False,
    judge_enabled: bool | None = None,
) -> dict[str, Any]:
    judges = judges or {}
    judge_requested = bool(judges) if judge_enabled is None else judge_enabled
    case_by_id = {c.id: c for c in cases}
    rows: list[dict[str, Any]] = []
    for driven in results:
        case = case_by_id.get(driven.trace.case_id)
        if case is None:
            continue
        # Repeated release attempts may have an independent Judge result;
        # callers can key those as ``case_id#attempt_no``.  Fall back to the
        # case key for single-attempt/debug runs.
        attempt_index = sum(1 for row in rows if row["case_id"] == case.id) + 1
        judge = judges.get(f"{case.id}#{attempt_index}") or judges.get(case.id)
        hard_pass = bool(driven.hard_eval.passed)
        judge_pass = judge.judge_pass if judge else None
        final = (
            hard_pass and judge_pass
            if judge_pass is not None
            else (
                hard_pass
                if not judge_requested
                and case.task_type not in {"long_tail_response_v1", "safety_response_v2"}
                else (hard_pass if case.task_type == "intent_route" else None)
            )
        )
        case_row = CaseReport(
            case.id,
            case.task_type,
            hard_pass,
            driven.hard_eval.hard_fail_reasons,
            driven.hard_eval.dimensions,
            final,
            judge_pass,
            judge.weighted_score if judge else None,
            judge.error_code if judge else None,
            judge.self_judged if judge else False,
            driven.runtime_error,
            judge_dimensions=judge.dimension_scores if judge else None,
            critical_violations=judge.critical_violations if judge else (),
            judge_input_hash=judge.input_hash if judge else None,
            judge_model=judge.model if judge else None,
            judge_summary=_sanitize(judge.rationale) if judge else None,
            judge_evidence=(
                tuple(str(item) for item in _sanitize(list(judge.evidence))) if judge else ()
            ),
            expected=_sanitize(case.expected.values),
            actual=_sanitize({
                "run_id": driven.trace.run_id,
                "route": driven.trace.route,
                "intent": driven.trace.intent,
                "next_action": driven.trace.next_action,
                "args": driven.trace.args,
                "tools_called": list(driven.trace.tools_called),
                "evidence_ids": list(driven.trace.evidence_ids),
                "status": driven.trace.status,
                "response_present": bool(driven.trace.response.strip()),
            }),
            e2e_latency_ms=driven.e2e_latency_ms,
            agent_invocation_count=driven.agent_invocation_count,
            agent_input_tokens=driven.agent_input_tokens,
            agent_output_tokens=driven.agent_output_tokens,
            agent_total_tokens=driven.agent_total_tokens,
            agent_cost_microusd=driven.agent_cost_microusd,
            agent_usage_estimated_count=driven.agent_usage_estimated_count,
            judge_latency_ms=judge.latency_ms if judge else None,
            judge_total_tokens=judge.usage_tokens if judge else None,
            judge_cost_microusd=judge.judge_cost_microusd if judge else None,
        )
        rows.append(asdict(case_row))
    track: dict[str, dict[str, int]] = defaultdict(
        lambda: {"selected": 0, "attempts": 0, "hard_pass": 0, "judge_pass": 0, "final_pass": 0}
    )
    by_track: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        by_track[row["track"]][row["case_id"]].append(row)
    for name, groups in by_track.items():
        item = track[name]
        item["selected"] = len(groups)
        item["attempts"] = sum(len(values) for values in groups.values())
        item["hard_pass"] = sum(int(values[0]["hard_pass"]) for values in groups.values() if values)
        item["judge_pass"] = sum(
            int(values[0]["judge_pass"] is True) for values in groups.values() if values
        )
        item["final_pass"] = sum(
            int(
                all(v["final_pass"] is True for v in values[:repetitions])
                and len(values) >= repetitions
            )
            for values in groups.values()
        )

    judge_dimension_stats, judge_score_stats = _judge_stats(rows)
    judge_enabled = judge_requested
    judge_incomplete = any(
        (
            r["track"] != "intent_route"
            and (
                not judge_requested
                or r["judge_error"]
                or r["judge_pass"] is None
            )
        )
        for r in rows
        if r["track"] in {
            "long_tail_response_v1",
            "safety_response_v2",
        }
    ) or (
        judge_enabled
        and any(
            r["judge_error"] or r["judge_pass"] is None
            for r in rows
            if r["track"] != "intent_route"
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["case_id"]].append(row)
    first_pass_rate = (
        sum(1 for values in grouped.values() if values and values[0]["final_pass"] is True)
        / len(grouped)
        if grouped
        else 0.0
    )
    all_pass_rate = (
        sum(
            1
            for values in grouped.values()
            if len(values) >= repetitions
            and all(v["final_pass"] is True for v in values[:repetitions])
        )
        / len(grouped)
        if grouped
        else 0.0
    )
    performance_stats = _performance_stats(rows)
    safety_stats = _safety_stats(rows)
    long_tail_stats = _long_tail_stats(rows)
    return {
        "schema_version": "2.0",
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "dataset_hash": dataset_hash,
        "manifest_hash": manifest_hash,
        "rubric_hash": rubric_hash,
        "runtime_hash": runtime_hash,
        "runtime": runtime,
        "runtime_versions": runtime_versions or {},
        # Synthetic generation may be an external model call in a future
        # pipeline. Keep it separate from Agent/Judge cost and preserve
        # unknown as NULL rather than presenting an invented zero.
        "synthesis_cost_microusd": synthesis_cost_microusd,
        "prompt_hash": prompt_hash,
        "mode": mode,
        "repetitions": repetitions,
        "concurrency": 1,
        "judge": "on" if judge_enabled else "off",
        "self_judged": any(r["self_judged"] for r in rows),
        "provisional": any(r["self_judged"] for r in rows),
        "release_gate": bool(
            mode == "release"
            and judge_enabled
            and not any(r["self_judged"] for r in rows)
            and not judge_incomplete
        ),
        "status": "cancelled" if cancelled else ("incomplete" if judge_incomplete else "completed"),
        "selected_cases": len(grouped),
        "completed_cases": len(grouped),
        "attempts": len(rows),
        "passed_cases": sum(
            1
            for values in grouped.values()
            if len(values) >= repetitions
            and all(r["final_pass"] is True for r in values[:repetitions])
        ),
        "failed_cases": sum(
            1
            for values in grouped.values()
            if len(values) < repetitions
            or not all(r["final_pass"] is True for r in values[:repetitions])
        ),
        "first_pass_rate": round(first_pass_rate, 4),
        "all_repetitions_pass_rate": round(all_pass_rate, 4),
        "hard_passed_cases": sum(
            1 for values in grouped.values() if values and values[0]["hard_pass"]
        ),
        "judge_passed_cases": sum(
            1 for values in grouped.values() if values and values[0]["judge_pass"] is True
        ),
        "judge_models": sorted({r["judge_model"] for r in rows if r["judge_model"]}),
        "tracks": dict(track),
        "judge_dimension_stats": dict(judge_dimension_stats),
        "judge_score_stats": dict(judge_score_stats),
        "performance_stats": performance_stats,
        "safety_stats": safety_stats,
        "long_tail_stats": long_tail_stats,
        "results": rows,
    }


def write_report(report: dict[str, Any], output_dir: Path | str) -> tuple[Path, Path]:
    # Also support re-rendering older JSON reports whose rows already contain
    # ``judge_dimensions`` but predate the aggregate fields.
    if "judge_dimension_stats" not in report or "judge_score_stats" not in report:
        dimension_stats, score_stats = _judge_stats(report.get("results", []))
        report = {
            **report,
            "judge_dimension_stats": dimension_stats,
            "judge_score_stats": score_stats,
        }
    if "performance_stats" not in report:
        report = {
            **report,
            "performance_stats": _performance_stats(report.get("results", [])),
        }
    if "safety_stats" not in report:
        report = {
            **report,
            "safety_stats": _safety_stats(report.get("results", [])),
        }
    if "long_tail_stats" not in report:
        report = {
            **report,
            "long_tail_stats": _long_tail_stats(report.get("results", [])),
        }
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "report.json"
    md_path = directory / "report.md"
    human_approval = report.get("human_approval")
    human_approval_status = (
        human_approval.get("status") if isinstance(human_approval, dict) else None
    )
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    lines = [
        "# CommerceAgent 评测报告",
        "",
        f"状态：`{report.get('status')}`",
        "",
        "## 评测证据版本",
        "",
        "| 字段 | 值 |",
        "|---|---|",
        f"| Runtime | {_display(report.get('runtime'))} |",
        f"| Dataset | {_display(report.get('dataset_id'))} |",
        f"| Dataset version | {_display(report.get('dataset_version'))} |",
        f"| Dataset hash | {_display(report.get('dataset_hash'))} |",
        f"| Manifest hash | {_display(report.get('manifest_hash'))} |",
        f"| Runtime hash | {_display(report.get('runtime_hash'))} |",
        f"| Prompt hash | {_display(report.get('prompt_hash'))} |",
        f"| Rubric hash | {_display(report.get('rubric_hash'))} |",
        f"| Source commit | {_display(report.get('source_commit'))} |",
        f"| Synthesis cost (μUSD) | {_display(report.get('synthesis_cost_microusd'))} |",
        f"| Human approval | {_display(human_approval_status)} |",
        "",
        f"总 case：{report.get('selected_cases', 0)}",
        f"最终通过：{report.get('passed_cases', 0)}",
        "",
        "## Track 指标",
        "",
        "| Track | Cases | Hard 通过 | Judge 通过 | Final 通过 |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, metric in report.get("tracks", {}).items():
        lines.append(
            f"| {name} | {metric['selected']} | {metric['hard_pass']} | "
            f"{metric['judge_pass']} | {metric['final_pass']} |"
        )
    lines.extend(
        [
            "",
            "## Judge 指标平均分",
            "",
            "评分范围为 0～4 分；平均分按每次 Judge 评估计算，重复运行按 attempt 分别计入。",
            "",
            "| 范围 | 指标 | 样本数 | 平均分 |",
            "|---|---|---:|---:|",
        ]
    )
    for scope, dimensions in report.get("judge_dimension_stats", {}).items():
        for name, metric in dimensions.items():
            lines.append(f"| {scope} | {name} | {metric['count']} | {metric['mean']:.4f} |")
    score_stats = report.get("judge_score_stats", {})
    if score_stats:
        lines.extend(
            [
                "",
                "## Judge 加权总分平均分",
                "",
                "| 范围 | 样本数 | 平均分 |",
                "|---|---:|---:|",
            ]
        )
        for scope, metric in score_stats.items():
            lines.append(f"| {scope} | {metric['count']} | {metric['mean']:.4f} |")
    lines.extend(
        [
            "",
            "## 时延、Token 与成本",
            "",
            "缺失的 Provider usage 或价格显示为 `N/A`，不会按 0 计入。Agent 与 Judge 分栏。",
            "",
            "| 范围 | 指标 | 样本数 | 平均值 | P50 | P95 | P99 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for scope, metrics in report.get("performance_stats", {}).items():
        for name, metric in metrics.items():
            if not isinstance(metric, dict) or "count" not in metric:
                continue
            lines.append(
                f"| {scope} | {name} | {metric['count']} | {_metric_value(metric, 'mean')} | "
                f"{_metric_value(metric, 'p50')} | {_metric_value(metric, 'p95')} | "
                f"{_metric_value(metric, 'p99')} |"
            )
    safety_stats = report.get("safety_stats", {})
    if safety_stats:
        lines.extend(
            [
                "",
                "## Safety Gate 指标",
                "",
                "高危 Track 的 hard fail 按 P0 处理；缺失数据不会按 0 计入。",
                "",
                "| 指标 | 数值 |",
                "|---|---:|",
                f"| 高危样本数 | {safety_stats.get('high_risk_cases', 0)} |",
                f"| P0 hard fail | {safety_stats.get('p0_failure_count', 0)} |",
                f"| safe_next_step 失败 | {safety_stats.get('safe_next_step_failure_count', 0)} |",
            ]
        )
    long_tail_stats = report.get("long_tail_stats", {})
    if long_tail_stats:
        lines.extend(
            [
                "",
                "## 低风险长尾承接",
                "",
                "该统计只反映当前评测 Runtime；没有真人标注时不能解释为线上误拒绝率。",
                "",
                "| 指标 | 数值 |",
                "|---|---:|",
                f"| 低风险样本数 | {long_tail_stats.get('low_risk_cases', 'N/A')} |",
                f"| 转人工样本数 | {long_tail_stats.get('handoff_count', 'N/A')} |",
                f"| 评测 Runtime 转人工率 | {_metric_value(long_tail_stats, 'handoff_rate')} |",
            ]
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def _performance_stats(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Aggregate observability fields without converting unknown values to zero."""

    metric_names = (
        "e2e_latency_ms",
        "agent_invocation_count",
        "agent_input_tokens",
        "agent_output_tokens",
        "agent_total_tokens",
        "agent_cost_microusd",
        "judge_latency_ms",
        "judge_total_tokens",
        "judge_cost_microusd",
    )
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        track_name = str(row.get("track", "unknown"))
        for scope in ("overall", track_name):
            for name in metric_names:
                samples = values[scope][name]
                value = row.get(name)
                if isinstance(value, int | float) and not isinstance(value, bool):
                    samples.append(float(value))
            invocations = row.get("agent_invocation_count")
            estimated = row.get("agent_usage_estimated_count")
            estimated_ratios = values[scope]["agent_estimated_usage_ratio"]
            if (
                isinstance(invocations, int)
                and isinstance(estimated, int)
                and invocations > 0
                and 0 <= estimated <= invocations
            ):
                estimated_ratios.append(estimated / invocations)
    return {
        scope: {name: _distribution(samples) for name, samples in metrics.items()}
        for scope, metrics in values.items()
    }


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "p99": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": round(sum(ordered) / len(ordered), 4),
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "p99": _percentile(ordered, 0.99),
    }


def _percentile(values: list[float], quantile: float) -> float:
    if len(values) == 1:
        return round(values[0], 4)
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return round(values[lower] + (values[upper] - values[lower]) * fraction, 4)


def _metric_value(metric: dict[str, Any], name: str) -> str:
    value = metric.get(name)
    if not isinstance(value, int | float) or isinstance(value, bool):
        return "N/A"
    return f"{value:.4f}"


def _display(value: object) -> str:
    """Render missing evidence as an explicit unknown, never as a fake value."""

    return str(value) if isinstance(value, str) and value else "N/A"


def _judge_stats(
    rows: Iterable[dict[str, Any]],
) -> tuple[dict[str, dict[str, dict[str, float | int]]], dict[str, dict[str, float | int]]]:
    """Aggregate Judge rubric scores for the JSON and Markdown reports."""

    # Keep rubric dimensions separated by track: dimensions such as
    # ``clarity`` can have different meanings in different rubrics. Counts
    # are Judge evaluations, so repeated runs contribute one observation per
    # attempt rather than being silently collapsed to one case.
    dimension_values: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    judge_score_values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        judge_dimensions = row.get("judge_dimensions") or {}
        if not judge_dimensions:
            continue
        track_name = str(row["track"])
        for scope in ("overall", track_name):
            for name, score in judge_dimensions.items():
                dimension_values[scope][str(name)].append(int(score))
            judge_score = row.get("judge_score")
            if judge_score is not None:
                judge_score_values[scope].append(float(judge_score))

    dimension_stats = {
        scope: {
            name: {"mean": round(sum(scores) / len(scores), 4), "count": len(scores)}
            for name, scores in dimensions.items()
        }
        for scope, dimensions in dimension_values.items()
    }
    score_stats = {
        scope: {"mean": round(sum(scores) / len(scores), 4), "count": len(scores)}
        for scope, scores in judge_score_values.items()
    }
    return dict(dimension_stats), dict(score_stats)


def _safety_stats(rows: Iterable[dict[str, Any]]) -> dict[str, int | float | bool]:
    """Return high-risk release-gate facts for the safety synthetic track."""

    safety_rows = [row for row in rows if row.get("track") == "safety_response_v2"]
    if not safety_rows:
        return {}
    safe_failures = sum(
        int((row.get("dimensions") or {}).get("safe_next_step") is False)
        for row in safety_rows
    )
    p0_failures = sum(int(not bool(row.get("hard_pass"))) for row in safety_rows)
    return {
        "high_risk_cases": len(safety_rows),
        "p0_failure_count": p0_failures,
        "safe_next_step_failure_count": safe_failures,
        "safe_next_step_critical_pass": safe_failures == 0,
        "safe_next_step_pass_rate": round(
            (len(safety_rows) - safe_failures) / len(safety_rows), 4
        ),
        "handoff_count": sum(
            int((row.get("actual") or {}).get("next_action") == "handoff")
            for row in safety_rows
        ),
    }


def _long_tail_stats(rows: Iterable[dict[str, Any]]) -> dict[str, int | float]:
    """Expose low-risk handoff observations without calling them labels."""

    long_tail_rows = [row for row in rows if row.get("track") == "long_tail_response_v1"]
    if not long_tail_rows:
        return {}
    handoff_count = sum(
        int((row.get("actual") or {}).get("next_action") in {"handoff", "wait_human"})
        for row in long_tail_rows
    )
    return {
        "low_risk_cases": len(long_tail_rows),
        "handoff_count": handoff_count,
        "handoff_rate": round(handoff_count / len(long_tail_rows), 4),
    }
