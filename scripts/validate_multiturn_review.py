"""Validate human labels against a multi-turn review queue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.harness.multiturn_review import (
    load_multiturn_review_labels,
    reviewed_multiturn_stats,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    try:
        labels = load_multiturn_review_labels(args.labels)
        stats = reviewed_multiturn_stats(
            queue.get("items", []),
            labels,
            minimum_count=int(queue.get("requested_count", 20)),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        stats = {
            "status": "incomplete",
            "error": "human_review_labels_unavailable",
            "error_type": type(error).__name__,
        }
    result = {
        "schema_version": "multiturn-human-review-stats-v1",
        "source_queue": str(args.queue),
        "source_labels": str(args.labels),
        "stats": stats,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0 if stats.get("status") == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
