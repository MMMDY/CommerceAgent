"""Audit the plan-level human-review and static-baseline evidence gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.harness.layered_evidence import audit_layered_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--human-review-stats", type=Path, required=True)
    parser.add_argument("--baseline-comparison", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-reviewed", type=int, default=20)
    parser.add_argument("--expected-cases", type=int, default=300)
    parser.add_argument("--expected-attempts", type=int, default=900)
    parser.add_argument(
        "--skip-human-review",
        action="store_true",
        help="Record an explicit human-review waiver for an automated-only audit",
    )
    parser.add_argument(
        "--waiver-reason",
        help="Required reason recorded with --skip-human-review",
    )
    args = parser.parse_args()
    try:
        human_review = _read_object(args.human_review_stats)
        comparison = _read_object(args.baseline_comparison)
        result = audit_layered_evidence(
            human_review,
            comparison,
            minimum_reviewed=args.minimum_reviewed,
            expected_cases=args.expected_cases,
            expected_attempts=args.expected_attempts,
            skip_human_review=args.skip_human_review,
            waiver_reason=args.waiver_reason,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        result = {
            "schema_version": "layered-evaluation-evidence-audit-v1",
            "status": "incomplete",
            "release_gate": False,
            "checks": {},
            "blocking_reasons": [f"input_unavailable:{type(error).__name__}"],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "complete" else 2


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
