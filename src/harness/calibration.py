"""Calibration-set loading and Judge agreement statistics."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.harness.judge import JudgeResult


class CalibrationLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    gold_pass: bool
    source: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)
    rubric_version: str = Field(min_length=1)
    label_hash: str = Field(min_length=1)


def load_labels(path: Path | str) -> tuple[CalibrationLabel, ...]:
    source = Path(path)
    rows = tuple(
        CalibrationLabel.model_validate_json(line)
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if len(rows) != 30:
        raise ValueError("calibration set must contain exactly 30 labels")
    if len({row.case_id for row in rows}) != len(rows):
        raise ValueError("calibration case identifiers must be unique")
    return rows


def calibration_report(
    labels: Iterable[CalibrationLabel],
    results: Iterable[JudgeResult],
    *,
    judge_model: str | None = None,
    prompt_hash: str | None = None,
    rubric_version: str | None = None,
) -> dict[str, Any]:
    by_id = {result.case_id: result for result in results}
    labels = tuple(labels)
    pairs = [
        (label, by_id[label.case_id])
        for label in labels
        if label.case_id in by_id and by_id[label.case_id].judge_pass is not None
    ]
    agreements = sum(int(label.gold_pass == result.judge_pass) for label, result in pairs)
    conflicts = [
        {"case_id": label.case_id, "gold_pass": label.gold_pass, "judge_pass": result.judge_pass}
        for label, result in pairs
        if label.gold_pass != result.judge_pass
    ]
    dimensions: dict[str, list[int]] = {}
    for _, result in pairs:
        for name, score in result.dimension_scores.items():
            dimensions.setdefault(name, []).append(score)
    dimension_stats = {
        name: {"mean": round(sum(scores) / len(scores), 4), "count": len(scores)}
        for name, scores in dimensions.items()
    }
    boundary_cases = [
        result.case_id
        for _, result in pairs
        if result.weighted_score is not None and 2.0 <= result.weighted_score < 3.5
    ]
    canonical = json.dumps(
        [label.model_dump() for label in labels],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "label_count": len(labels),
        "evaluated_count": len(pairs),
        "agreement_rate": round(agreements / len(pairs), 4) if pairs else None,
        "conflicts": conflicts,
        "boundary_cases": boundary_cases,
        "dimension_stats": dimension_stats,
        "judge_model": judge_model,
        "prompt_hash": prompt_hash,
        "rubric_version": rubric_version,
        "labels_hash": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        "status": "complete" if len(pairs) == len(labels) else "incomplete",
    }
