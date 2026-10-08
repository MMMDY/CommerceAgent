from pathlib import Path

import pytest
from fastapi import HTTPException

from apps.api import main


def test_eval_report_paths_accept_legacy_safe_report_names(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "EVAL_REPORT_ROOT", tmp_path)

    report_path, markdown_path = main._eval_report_paths("baseline-20260918")

    assert report_path == tmp_path / "baseline-20260918" / "report.json"
    assert markdown_path == tmp_path / "baseline-20260918" / "report.md"


@pytest.mark.parametrize("value", ["../secrets", "/tmp/report", "", "a/../../b", "a" * 129])
def test_eval_report_paths_reject_path_traversal_and_invalid_names(value: str) -> None:
    with pytest.raises(HTTPException) as error:
        main._eval_report_paths(value)

    assert error.value.status_code == 404
