from __future__ import annotations

import json
from pathlib import Path

from src.config import Settings
from src.harness import live_runner

LONG_TAIL_DATASET = Path("evals/long_tail_zh/cases.jsonl")


def test_live_runner_without_explicit_acknowledgement_is_incomplete(
    capsys: object, tmp_path: Path
) -> None:
    result = live_runner.main(
        (
            "--dataset",
            str(LONG_TAIL_DATASET),
            "--judge",
            "off",
            "--output-dir",
            str(tmp_path),
        )
    )

    assert result == 2
    report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert report["status"] == "incomplete"
    assert report["runtime"] == "live_model"
    assert report["judge"] == "off"
    assert report["incomplete_reason"] == "live_execution_requires_--allow-live"
    assert (tmp_path / "report.md").is_file()


def test_live_runner_missing_configuration_never_falls_back_to_fixture(
    capsys: object, tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setattr(live_runner, "get_settings", lambda: Settings(_env_file=None))  # type: ignore[attr-defined]

    result = live_runner.main(
        (
            "--dataset",
            str(LONG_TAIL_DATASET),
            "--allow-live",
            "--judge",
            "off",
            "--output-dir",
            str(tmp_path),
        )
    )

    assert result == 2
    report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert report["status"] == "incomplete"
    assert report["runtime"] == "live_model"
    assert report["incomplete_reason"] == "LiveConfigurationError"
    assert report["results"] == []
