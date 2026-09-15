"""Deterministic aggregation and serialization of evaluation results."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from collections.abc import Iterable
from typing import Any

from src.harness.judge import JudgeResult
from src.harness.run_driver import DrivenCase
from src.harness.schema import EvalCase


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
    latency_ms: int | None = None
    token_usage: int | None = None
    judge_dimensions: dict[str, int] | None = None
    critical_violations: tuple[str, ...] = ()
    judge_input_hash: str | None = None
    judge_model: str | None = None
    expected: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None


def build_report(
    cases: Iterable[EvalCase],
    results: Iterable[DrivenCase],
    *,
    judges: dict[str, JudgeResult] | None = None,
    dataset_hash: str | None = None,
    runtime_hash: str | None = None,
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
        judge = judges.get(case.id)
        hard_pass = bool(driven.hard_eval.passed)
        judge_pass = judge.judge_pass if judge else None
        final = hard_pass and judge_pass if judge_pass is not None else (hard_pass if not judge_requested or case.task_type == "intent_route" else None)
        row = CaseReport(
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
            expected=case.expected.values,
            actual={
                "route": driven.trace.route,
                "intent": driven.trace.intent,
                "next_action": driven.trace.next_action,
                "args": driven.trace.args,
                "tools_called": list(driven.trace.tools_called),
                "evidence_ids": list(driven.trace.evidence_ids),
                "status": driven.trace.status,
            },
        )
        rows.append(asdict(row))
    track = defaultdict(lambda: {"selected": 0, "hard_pass": 0, "judge_pass": 0, "final_pass": 0})
    for row in rows:
        item = track[row["track"]]
        item["selected"] += 1
        item["hard_pass"] += int(row["hard_pass"])
        item["judge_pass"] += int(row["judge_pass"] is True)
        item["final_pass"] += int(row["final_pass"] is True)
    judge_enabled = judge_requested
    judge_incomplete = judge_enabled and any(r["judge_error"] or r["judge_pass"] is None for r in rows if r["track"] != "intent_route")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["case_id"]].append(row)
    first_pass_rate = (
        sum(1 for values in grouped.values() if values and values[0]["final_pass"] is True) / len(grouped)
        if grouped else 0.0
    )
    all_pass_rate = (
        sum(1 for values in grouped.values() if len(values) >= repetitions and all(v["final_pass"] is True for v in values[:repetitions])) / len(grouped)
        if grouped else 0.0
    )
    return {
        "schema_version": "1.0",
        "dataset_hash": dataset_hash,
        "runtime_hash": runtime_hash,
        "mode": mode,
        "repetitions": repetitions,
        "concurrency": 1,
        "judge": "on" if judge_enabled else "off",
        "self_judged": any(r["self_judged"] for r in rows),
        "provisional": any(r["self_judged"] for r in rows),
        "status": "cancelled" if cancelled else ("incomplete" if judge_incomplete else "completed"),
        "selected_cases": len(rows),
        "completed_cases": len(rows),
        "passed_cases": sum(1 for r in rows if r["final_pass"] is True),
        "failed_cases": sum(1 for r in rows if r["final_pass"] is not True),
        "first_pass_rate": round(first_pass_rate, 4),
        "all_repetitions_pass_rate": round(all_pass_rate, 4),
        "hard_passed_cases": sum(1 for r in rows if r["hard_pass"]),
        "judge_passed_cases": sum(1 for r in rows if r["judge_pass"] is True),
        "judge_models": sorted({r["judge_model"] for r in rows if r["judge_model"]}),
        "tracks": dict(track),
        "results": rows,
    }


def write_report(report: dict[str, Any], output_dir: Path | str) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "report.json"
    md_path = directory / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    lines = ["# CommerceAgent 评测报告", "", f"状态：`{report.get('status')}`", f"总 case：{report.get('selected_cases', 0)}", f"最终通过：{report.get('passed_cases', 0)}", "", "## Track 指标", "", "| Track | Cases | Hard 通过 | Judge 通过 | Final 通过 |", "|---|---:|---:|---:|---:|"]
    for name, metric in report.get("tracks", {}).items():
        lines.append(f"| {name} | {metric['selected']} | {metric['hard_pass']} | {metric['judge_pass']} | {metric['final_pass']} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
