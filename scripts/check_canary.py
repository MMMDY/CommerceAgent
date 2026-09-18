#!/usr/bin/env python3
"""Evaluate one progressive-release observation window and advance one stage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from src.db import get_engine
from src.release.canary_guard import CanaryMetrics, evaluate_canary
from src.release.report import build_release_markdown
from src.repositories.releases import ReleaseRepository, ReleaseTransitionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_id", type=UUID)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--tenant-id", default="demo-tenant")
    parser.add_argument("--actor-ref", default="canary-scheduler")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--markdown-report", type=Path)
    parser.add_argument("--current-version", default="unknown")
    parser.add_argument("--candidate-version", default="unknown")
    parser.add_argument("--stage", default="unknown")
    args = parser.parse_args(argv)
    try:
        metrics = CanaryMetrics(**json.loads(args.metrics.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"canary-check failed: invalid_metrics ({error})", file=sys.stderr)
        return 2
    decision = evaluate_canary(metrics)
    result: dict[str, object] | None = None
    if args.dry_run:
        result = {"stop": decision.stop, "reasons": decision.reasons}
    else:
        try:
            result = ReleaseRepository(get_engine()).evaluate_and_advance(
                tenant_id=args.tenant_id,
                release_id=args.release_id,
                actor_ref=args.actor_ref,
                metrics=metrics,
            )
        except ReleaseTransitionError as error:
            print(f"canary-check failed: {error}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, default=str))
    if args.markdown_report is not None:
        try:
            args.markdown_report.write_text(
                build_release_markdown(
                    release_id=str(args.release_id),
                    current_version=str(
                        (result or {}).get("current_version", args.current_version)
                    ),
                    candidate_version=str(
                        (result or {}).get("candidate_version", args.candidate_version)
                    ),
                    stage=str((result or {}).get("stage", args.stage)),
                    decision=decision,
                    metrics=metrics,
                ),
                encoding="utf-8",
            )
        except OSError as error:
            print(f"canary-check failed: report_write ({error})", file=sys.stderr)
            return 1
    if args.dry_run:
        print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
