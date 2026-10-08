#!/usr/bin/env python3
"""Freeze a seven-day SLO baseline from redacted JSON samples."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from src.release.slo_baseline import BaselineSample, freeze_baseline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples", type=Path, help="JSON array or JSONL redacted samples")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--minimum-samples", type=int, default=100)
    args = parser.parse_args(argv)
    payload = _read_payload(args.samples)
    baseline = freeze_baseline(
        (BaselineSample(occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
                        e2e_latency_ms=_number(row.get("e2e_latency_ms")),
                        cost_microusd=_number(row.get("cost_microusd")),
                        low_risk_handoff_rate=_number(row.get("low_risk_handoff_rate")),
                        terminal_response_coverage=_number(row.get("terminal_response_coverage")))
         for row in payload),
        timezone=args.timezone,
        minimum_samples=args.minimum_samples,
    )
    rendered = json.dumps(baseline.as_dict(), ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps(baseline.as_dict(), ensure_ascii=False))
    return 0


def _read_payload(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _number(value: object) -> float | None:
    return float(value) if value is not None else None


if __name__ == "__main__":
    raise SystemExit(main())
