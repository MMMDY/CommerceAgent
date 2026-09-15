from pathlib import Path

import pytest

from src.harness.resources import InsufficientDiskError, ensure_disk_budget


def test_disk_budget_rejects_unavailable_capacity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Usage:
        free = 10

    monkeypatch.setattr("src.harness.resources.shutil.disk_usage", lambda _path: Usage())
    with pytest.raises(InsufficientDiskError, match="insufficient_disk_capacity"):
        ensure_disk_budget(tmp_path, minimum_bytes=11)


def test_disk_budget_returns_available_capacity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Usage:
        free = 20

    monkeypatch.setattr("src.harness.resources.shutil.disk_usage", lambda _path: Usage())
    assert ensure_disk_budget(tmp_path, minimum_bytes=11) == 20
