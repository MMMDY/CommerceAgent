from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_operational_scripts_have_valid_shell_syntax() -> None:
    scripts = (
        "scripts/backup_db.sh",
        "scripts/restore_db.sh",
        "scripts/soak_monitor.sh",
        "scripts/cleanup_reports.sh",
        "scripts/collect_release_evidence.sh",
        "scripts/release_smoke.sh",
    )
    result = subprocess.run(
        ["bash", "-n", *scripts], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_soak_monitor_detach_status_and_stop(tmp_path: Path) -> None:
    output = tmp_path / "soak.json"
    command = [
        "scripts/soak_monitor.sh",
        "--duration",
        "1s",
        "--interval",
        "1",
        "--output",
        str(output),
        "--detach",
    ]
    started = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(started.stdout)["status"] == "running"
    # The worker is intentionally detached; status must be readable without
    # holding the test process open.
    for _ in range(20):
        status = subprocess.run(
            ["scripts/soak_monitor.sh", "--status", "--output", str(output)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        if output.is_file():
            payload = json.loads(status.stdout)
            if payload.get("status") == "completed":
                break
        time.sleep(0.1)
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] in {"completed", "stopped"}
    assert payload["samples"]


def test_release_checker_fails_closed_without_independent_judge(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "mode": "debug",
                "status": "completed",
                "self_judged": True,
                "release_gate": False,
                "selected_cases": 300,
                "attempts": 900,
                "calibration": {"agreement_rate": 1.0},
                "source_commit": "wrong",
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "scripts/release_check.py", str(report)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "judge_not_independent" in result.stderr
