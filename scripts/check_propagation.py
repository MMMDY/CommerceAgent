#!/usr/bin/env python3
"""Check redacted rollback/kill-switch propagation evidence."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from src.release.propagation import PropagationEvidence, evaluate_propagation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--deadline-seconds", type=float, default=60.0)
    args = parser.parse_args(argv)
    payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    evidence = PropagationEvidence(
        action=str(payload["action"]),
        control_changed_at=datetime.fromisoformat(str(payload["control_changed_at"])),
        first_post_change_request_at=(
            datetime.fromisoformat(str(payload["first_post_change_request_at"]))
            if payload.get("first_post_change_request_at")
            else None
        ),
        forbidden_matches_after_change=int(
            payload.get("forbidden_matches_after_change", 0)
        ),
        historical_run_reference_preserved=(
            payload.get("historical_run_reference_preserved")
            if isinstance(payload.get("historical_run_reference_preserved"), bool)
            else None
        ),
    )
    result = evaluate_propagation(evidence, deadline_seconds=args.deadline_seconds)
    print(json.dumps(result.as_dict(), ensure_ascii=False))
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
