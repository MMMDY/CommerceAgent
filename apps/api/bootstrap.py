"""Explicit, testable dependencies for API readiness probes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.config import get_settings
from src.db import check_ready
from src.orchestration.readiness import RuntimeRegistrationContainer

ReadinessProbe = Callable[[], tuple[bool, str]]


@dataclass(frozen=True, slots=True)
class ReadinessDependencies:
    """All dependencies allowed to participate in ``/health/ready``."""

    database: ReadinessProbe
    runtime: RuntimeRegistrationContainer

    @classmethod
    def default(cls) -> ReadinessDependencies:
        """Build a fail-closed container until real Runtime bootstrap is supplied."""

        return cls(
            database=check_ready,
            runtime=RuntimeRegistrationContainer.unconfigured(settings=get_settings()),
        )

    def check(self) -> tuple[bool, str]:
        """Check both dependency groups and return a stable, non-sensitive reason."""

        database_ready, database_reason = self.database()
        runtime_ready, runtime_reason = self.runtime.check()
        if not database_ready:
            return False, database_reason
        if not runtime_ready:
            return False, runtime_reason
        return True, "ready"
