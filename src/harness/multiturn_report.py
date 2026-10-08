"""Aggregation and persistence for multi-turn reports."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.harness.multiturn_schema import MultiTurnReport
from src.harness.multiturn_judge import MultiTurnJudgeResult
from src.telemetry.trace import _sanitize


def build_multiturn_report(
    reports: list[MultiTurnReport] | tuple[MultiTurnReport, ...],
    *,
    dataset_id: str = "multiturn",
    dataset_version: str = "candidate",
    runtime: str = "deterministic",
    judge_results: Mapping[str, MultiTurnJudgeResult | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    items = list(reports)
    valid = [item for item in items if item.status != "incomplete"]
    metric = lambda name: _metric(
        [getattr(item, name) for item in valid],
        f"multiturn.{name}",
        runtime=runtime,
    )
    exposed = [item.exposed_intent_accuracy for item in valid if item.exposed_intent_accuracy is not None and not item.evaluation_noise]
    task_values = [item.task_success for item in valid if item.task_success is not None]
    feedback = Counter(signal.category for item in items for signal in item.feedback)
    judge_rows = _judge_rows(judge_results)
    report_rows = []
    for item in items:
        row = _sanitize(item.model_dump(mode="json"))
        judge = judge_rows.get(item.scenario_id)
        if judge is not None:
            row["judge"] = judge
        report_rows.append(row)
    result = {
        "schema_version": "multiturn-report-v1",
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "runtime": runtime,
        "simulator_config": next(
            (
                item.metadata.get("simulator")
                for item in items
                if isinstance(item.metadata.get("simulator"), dict)
            ),
            None,
        ),
        "status": "incomplete" if len(valid) != len(items) else "completed",
        "release_gate": False,
        "gate_status": "candidate_only",
        "scenario_count": len(items),
        "dialogue_count": len(items),
        "completed_count": sum(item.status == "completed" for item in items),
        "incomplete_count": sum(item.status == "incomplete" for item in items),
        "evaluation_noise_count": sum(item.evaluation_noise for item in items),
        "intent_coverage": metric("intent_coverage"),
        "agenda_progress": metric("agenda_progress"),
        "exposed_intent_accuracy": _metric(
            exposed,
            "multiturn.exposed_intent_accuracy",
            runtime=runtime,
        ),
        "task_success_rate": _metric(
            task_values,
            "multiturn.task_success_rate",
            runtime=runtime,
        ),
        "termination_reasons": dict(Counter(item.termination_reason for item in items)),
        "feedback_categories": dict(feedback),
        "reports": report_rows,
    }
    if judge_results is not None:
        result["judge"] = _aggregate_judges(judge_rows, expected_count=len(items))
        if result["judge"]["status"] != "complete":
            result["status"] = "incomplete"
    return result


def write_multiturn_report(report: dict[str, Any], output_dir: Path | str) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "multiturn-report.json"
    markdown_path = target / "multiturn-report.md"
    json_path.write_text(json.dumps(_sanitize(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Multi-turn Evaluation Report",
        "",
        f"- Status: `{report.get('status', 'incomplete')}`",
        f"- Scenarios: {report.get('scenario_count', 0)}",
        f"- Evaluation noise: {report.get('evaluation_noise_count', 0)}",
        "",
        "| Metric | Mean / Rate | Count |",
        "|---|---:|---:|",
    ]
    for name in ("intent_coverage", "agenda_progress", "exposed_intent_accuracy", "task_success_rate"):
        value = report.get(name) or {}
        lines.append(f"| {name} | {value.get('mean', 'N/A')} | {value.get('count', 0)} |")
    lines.extend(["", "## Termination Reasons", ""])
    for reason, count in sorted((report.get("termination_reasons") or {}).items()):
        lines.append(f"- `{reason}`: {count}")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def _metric(values: list[Any], metric_id: str, *, runtime: str) -> dict[str, Any]:
    numeric = [
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else float(value)
        for value in values
        if isinstance(value, (int, float, bool))
    ]
    return {
        "mean": round(sum(numeric) / len(numeric), 4) if numeric else None,
        "count": len(numeric),
        "metric_id": metric_id,
        "numerator": round(sum(numeric), 4) if numeric else None,
        "denominator": len(numeric),
        "dataset_scope": "multiturn",
        "runtime": runtime,
        "evidence_status": "complete" if numeric else "incomplete",
        "confidence_note": "simulator and agent denominators are kept separate",
    }


def _judge_rows(
    values: Mapping[str, MultiTurnJudgeResult | Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    if values is None:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for scenario_id, value in values.items():
        row = value.model_dump() if isinstance(value, MultiTurnJudgeResult) else dict(value)
        row["scenario_id"] = str(row.get("scenario_id", scenario_id))
        rows[str(scenario_id)] = _sanitize(row)
    return rows


def _aggregate_judges(rows: Mapping[str, Mapping[str, Any]], *, expected_count: int) -> dict[str, Any]:
    scores = [
        float(row["weighted_score"])
        for row in rows.values()
        if isinstance(row.get("weighted_score"), (int, float))
    ]
    passed = sum(row.get("judge_pass") is True for row in rows.values())
    errors = sum(row.get("error_code") is not None for row in rows.values())
    return {
        "rubric_id": next(
            (str(row["rubric_id"]) for row in rows.values() if row.get("rubric_id")),
            None,
        ),
        "model": next((str(row["model"]) for row in rows.values() if row.get("model")), None),
        "scenario_count": expected_count,
        "evaluated_count": len(scores),
        "passed": passed,
        "failed": sum(row.get("judge_pass") is False for row in rows.values()),
        "error_count": errors,
        "mean_weighted_score": round(sum(scores) / len(scores), 4) if scores else None,
        "status": "complete" if len(rows) == expected_count and errors == 0 and len(scores) == expected_count else "incomplete",
        "evidence_status": "complete" if len(scores) == expected_count else "incomplete",
    }


__all__ = ["build_multiturn_report", "write_multiturn_report"]
