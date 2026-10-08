"""Independent catalog-track aggregation."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.harness.catalog_schema import CatalogEvaluation


def build_catalog_report(
    evaluations: list[CatalogEvaluation] | tuple[CatalogEvaluation, ...],
    *,
    dataset_id: str = "long_tail_catalog",
    dataset_version: str = "candidate",
    runtime: str = "deterministic",
) -> dict[str, Any]:
    items = list(evaluations)
    by_track: dict[str, list[CatalogEvaluation]] = {}
    for item in items:
        by_track.setdefault(item.task_type, []).append(item)
    selection = by_track.get("catalog_selection_v1", [])
    response = by_track.get("catalog_response_v1", [])
    safety = by_track.get("catalog_safety_v1", [])
    return {
        "schema_version": "catalog-report-v1",
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "runtime": runtime,
        "status": "incomplete" if any(item.evidence_status == "incomplete" for item in items) else "completed",
        "release_gate": False,
        "gate_status": "candidate_only",
        "catalog_stats": {
            "selection": {
                "case_count": len(selection),
                "top1": _bool_metric(selection, "top1_pass", "catalog.selection.top1"),
                "constraint_satisfaction": _bool_metric(selection, "constraint_satisfaction", "catalog.selection.constraint_satisfaction"),
                "trap_rejection": _bool_metric(selection, "trap_rejection", "catalog.selection.trap_rejection"),
            },
            "response": {
                "case_count": len(response),
                "evidence_grounding": _mean_metric(response, "evidence_grounding", "catalog.response.evidence_grounding"),
                "unsupported_claim_count": sum(item.unsupported_claim_count for item in response),
            },
            "safety": {
                "case_count": len(safety),
                "none_of_candidates_accuracy": _bool_metric(safety, "safety_pass", "catalog.safety.none_of_candidates_accuracy"),
                "forbidden_action_count": sum("catalog_safety_warning_or_deescalation_missing" in item.hard_fail_reasons for item in safety),
            },
            "slices": {
                "by_failure_type": {},
                "by_trap_family": {},
                "by_domain": {},
            },
        },
        "failure_reasons": dict(Counter(reason for item in items for reason in item.hard_fail_reasons)),
        "evaluations": [item.model_dump(mode="json") for item in items],
    }


def write_catalog_report(report: dict[str, Any], output_dir: Path | str) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "catalog-report.json"
    markdown_path = target / "catalog-report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stats = report.get("catalog_stats", {})
    lines = ["# Catalog Evaluation Report", "", f"- Status: `{report.get('status', 'incomplete')}`", "", "| Track | Cases | Metric |", "|---|---:|---:|"]
    for track, values in stats.items():
        if not isinstance(values, dict):
            continue
        for metric, value in values.items():
            if isinstance(value, dict) and "rate" in value:
                lines.append(f"| {track} | {value.get('total', 0)} | {metric}: {value.get('rate')} |")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def _bool_metric(items: list[CatalogEvaluation], field: str, metric_id: str) -> dict[str, Any]:
    values = [getattr(item, field) for item in items if getattr(item, field) is not None]
    passed = sum(value is True for value in values)
    return {
        "passed": passed,
        "total": len(values),
        "rate": round(passed / len(values), 4) if values else None,
        "metric_id": metric_id,
        "numerator": passed,
        "denominator": len(values),
        "dataset_scope": "long_tail_catalog",
        "runtime": "catalog_runner",
        "evidence_status": "complete" if values else "incomplete",
        "confidence_note": "closed candidate set; not full-catalog retrieval",
    }


def _mean_metric(items: list[CatalogEvaluation], field: str, metric_id: str) -> dict[str, Any]:
    values = [getattr(item, field) for item in items if isinstance(getattr(item, field), (int, float))]
    return {
        "mean": round(sum(values) / len(values), 4) if values else None,
        "count": len(values),
        "metric_id": metric_id,
        "numerator": round(sum(values), 4) if values else None,
        "denominator": len(values),
        "dataset_scope": "long_tail_catalog",
        "runtime": "catalog_runner",
        "evidence_status": "complete" if values else "incomplete",
        "confidence_note": "claim evidence references product_id and spec_key",
    }


__all__ = ["build_catalog_report", "write_catalog_report"]
