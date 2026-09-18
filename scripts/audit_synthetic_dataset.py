#!/usr/bin/env python3
"""Audit a candidate/frozen synthetic JSONL dataset without calling a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from src.synthesis.contracts import SyntheticCaseCandidate
from src.synthesis.splits import split_by_seed_family
from src.synthesis.validators import validate_candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    candidates: list[SyntheticCaseCandidate] = []
    errors: list[str] = []
    for number, line in enumerate(args.dataset.read_text(encoding="utf-8").splitlines(), 1):
        try:
            candidates.append(SyntheticCaseCandidate.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError, OSError) as error:
            errors.append(f"line {number}: {type(error).__name__}")
    if not errors:
        try:
            validate_candidates(candidates)
            manifest_path = args.dataset.parent / "manifest.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                assignments = manifest.get("seed_family_splits")
                if assignments is not None:
                    split_by_seed_family(candidates, assignments)
        except ValueError as error:
            errors.append(str(error))
    result = {
        "schema_version": "1.0",
        "status": "passed" if not errors else "failed",
        "sample_count": len(candidates),
        "error_count": len(errors),
        "errors": errors,
        "known_limitations": [
            "本地审计不替代独立 Critic 与高危样本真人审批",
            "候选集未自动进入线上 Skill 或生产流量",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
