from __future__ import annotations

import json
from pathlib import Path

from scripts.check_canary import main


def test_check_canary_dry_run_evaluates_metrics_without_database(tmp_path: Path) -> None:
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps({"terminal_response_coverage": 1.0}), encoding="utf-8")

    assert (
        main(
            [
                "00000000-0000-0000-0000-000000000001",
                "--metrics",
                str(metrics),
                "--dry-run",
            ]
        )
        == 0
    )


def test_check_canary_writes_redacted_current_candidate_markdown_report(tmp_path: Path) -> None:
    metrics = tmp_path / "metrics.json"
    metrics.write_text(
        json.dumps(
            {
                "terminal_response_coverage": 1.0,
                "baseline_p95_e2e_ms": 100.0,
                "p95_e2e_ms": 130.0,
                "current_route": "readonly",
                "candidate_route": "readonly",
                "current_response_policy": "execute",
                "candidate_response_policy": "execute",
                "current_skill": "none",
                "candidate_skill": "skill-v2",
            }
        ),
        encoding="utf-8",
    )
    report = tmp_path / "release.md"

    assert (
        main(
            [
                "00000000-0000-0000-0000-000000000001",
                "--metrics",
                str(metrics),
                "--dry-run",
                "--markdown-report",
                str(report),
                "--current-version",
                "v1",
                "--candidate-version",
                "v2",
                "--stage",
                "CANARY_5",
            ]
        )
        == 0
    )
    content = report.read_text(encoding="utf-8")
    assert "Current: `v1`" in content
    assert "Candidate: `v2`" in content
    assert "Automatic stop: **STOPPED**" in content
    assert "## Gate details" in content
    assert "P95 E2E" in content
    assert "STOP / INCOMPLETE" in content
    assert "readonly" in content
    assert "Prompt" not in content
    assert "tool_args" not in content
