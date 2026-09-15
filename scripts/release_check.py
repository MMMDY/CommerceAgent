#!/usr/bin/env python3
"""Fail-closed validation for an internal-beta release evidence report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def current_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("release-check failed: report_unavailable", file=sys.stderr)
        return 1
    failures: list[str] = []
    if report.get("mode") != "release":
        failures.append("mode_not_release")
    if report.get("status") != "completed":
        failures.append("status_not_completed")
    if report.get("self_judged") is not False or report.get("release_gate") is not True:
        failures.append("judge_not_independent")
    if report.get("selected_cases") != 300 or report.get("attempts") != 900:
        failures.append("case_count_incomplete")
    agreement = report.get("calibration", {}).get("agreement_rate")
    if agreement is None or agreement < 0.9:
        failures.append("calibration_below_threshold")
    if report.get("source_commit") != current_commit():
        failures.append("source_commit_mismatch")
    if args.require_clean:
        clean = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
        )
        if clean.returncode != 0 or clean.stdout.strip():
            failures.append("worktree_not_clean")
    if failures:
        print("release-check failed: " + ",".join(failures), file=sys.stderr)
        return 1
    print("release-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
