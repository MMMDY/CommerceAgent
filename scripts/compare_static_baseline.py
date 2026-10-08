"""Compare a current static evaluation report with a historical report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.harness.static_baseline import compare_static_baselines


def comparison_exit_code(result: dict[str, object]) -> int:
    """Fail the command when only a partial hard/runtime comparison exists."""

    return int(
        not (
            result.get("status") == "invariant_preserved"
            and result.get("evidence_status") == "complete"
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    historical = json.loads(args.historical.read_text(encoding="utf-8"))
    current = json.loads(args.current.read_text(encoding="utf-8"))
    result = compare_static_baselines(historical, current)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return comparison_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
