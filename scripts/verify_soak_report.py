#!/usr/bin/env python3
"""Validate a completed bounded soak report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def parse_duration(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)([smh])", value)
    if match is None:
        raise ValueError("duration must use Ns/Nm/Nh")
    amount = int(match.group(1))
    multiplier = {"s": 1, "m": 60, "h": 3600}[match.group(2)]
    return amount * multiplier


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a completed bounded soak report")
    parser.add_argument("report", type=Path)
    parser.add_argument("--min-duration", default="10m")
    parser.add_argument("--min-samples", type=int, default=10)
    parser.add_argument("--max-errors", type=int, default=0)
    args = parser.parse_args()

    try:
        minimum_duration = parse_duration(args.min_duration)
        payload = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"soak-check failed: {exc}", file=sys.stderr)
        return 1

    failures: list[str] = []
    if payload.get("schema_version") != "1.0":
        failures.append("schema_version_invalid")
    if payload.get("status") != "completed":
        failures.append("status_not_completed")
    samples = payload.get("samples")
    if not isinstance(samples, list):
        failures.append("samples_missing")
        samples = []
    if len(samples) < args.min_samples:
        failures.append("sample_count_below_threshold")

    elapsed_values: list[int] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            failures.append(f"sample_{index}_invalid")
            continue
        elapsed = sample.get("elapsed_seconds")
        if not isinstance(elapsed, int) or elapsed < 0:
            failures.append(f"sample_{index}_elapsed_invalid")
        else:
            elapsed_values.append(elapsed)
        for field in ("memory_bytes", "disk_free_bytes", "error_count"):
            if sample.get(field) is None:
                failures.append(f"sample_{index}_{field}_missing")
        if not isinstance(sample.get("error_count"), int):
            failures.append(f"sample_{index}_error_count_invalid")

    if elapsed_values:
        if elapsed_values != sorted(elapsed_values):
            failures.append("elapsed_not_monotonic")
        if elapsed_values[-1] < minimum_duration:
            failures.append("duration_below_threshold")
    else:
        failures.append("elapsed_missing")
    if any(
        isinstance(sample, dict)
        and isinstance(sample.get("error_count"), int)
        and sample["error_count"] > args.max_errors
        for sample in samples
    ):
        failures.append("error_count_above_threshold")

    if failures:
        print("soak-check failed: " + ",".join(dict.fromkeys(failures)), file=sys.stderr)
        return 1
    print(
        f"soak-check passed: {len(samples)} samples, "
        f"{elapsed_values[-1]} seconds, max_errors={args.max_errors}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
