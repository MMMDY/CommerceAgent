"""Resource admission checks for evaluation and report retention."""

from __future__ import annotations

import shutil
from pathlib import Path


class InsufficientDiskError(RuntimeError):
    """Raised before starting work when the report volume is too full."""


def ensure_disk_budget(path: Path | str, *, minimum_bytes: int = 3 * 1024**3) -> int:
    if minimum_bytes <= 0:
        raise ValueError("minimum_bytes must be positive")
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    available = shutil.disk_usage(target).free
    if available < minimum_bytes:
        raise InsufficientDiskError("insufficient_disk_capacity")
    return available


__all__ = ["InsufficientDiskError", "ensure_disk_budget"]
