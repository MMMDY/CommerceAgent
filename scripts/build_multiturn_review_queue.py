"""Create a pending human review queue from a multi-turn report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.harness.multiturn_review import build_multiturn_review_queue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=20)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    queue = build_multiturn_review_queue(report, sample_size=args.sample_size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: queue[key] for key in ("status", "requested_count", "reviewed_count")},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
