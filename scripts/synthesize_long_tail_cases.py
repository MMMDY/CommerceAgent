#!/usr/bin/env python3
"""Generate deterministic long-tail candidates; output is not a frozen set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.synthesis.generator import generate_long_tail
from src.synthesis.validators import validate_candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default="long-tail-v1")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.count <= 1000:
        parser.error("--count must be between 1 and 1000")
    candidates = validate_candidates(generate_long_tail(seed=args.seed, count=args.count))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False) for item in candidates
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "candidate", "count": len(candidates)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
