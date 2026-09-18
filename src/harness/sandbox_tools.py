"""Safety boundary for live evaluation tool execution.

Live evaluation may exercise the model's decision to prepare a mutation, but
it must never commit a business-side effect.  This module is deliberately
small and independent from the production mutation workflow so a future live
runner cannot accidentally reuse a commit adapter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from src.protocols import ToolRisk, ToolSpec


class SandboxCommitBlocked(RuntimeError):
    """Raised when a live evaluation attempts to cross the commit boundary."""


@dataclass(frozen=True, slots=True)
class SandboxPreparation:
    """Non-sensitive record of a mutation preparation request."""

    tool_name: str
    tool_version: str
    arguments_hash: str
    committed: bool = False


class SandboxToolPolicy:
    """Allow only read tools and prepare-only mutation boundaries."""

    def validate(self, spec: ToolSpec) -> None:
        if spec.risk is ToolRisk.COMMIT:
            raise SandboxCommitBlocked("live evaluation cannot execute commit tools")

    def prepare(self, *, spec: ToolSpec, arguments: dict[str, Any]) -> SandboxPreparation:
        self.validate(spec)
        if spec.risk not in {ToolRisk.PREPARE, ToolRisk.LOW_WRITE}:
            raise ValueError("only mutation tools can be sandbox-prepared")
        serialized = json.dumps(
            arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return SandboxPreparation(
            tool_name=spec.name,
            tool_version=spec.version,
            arguments_hash=f"sha256:{sha256(serialized.encode()).hexdigest()}",
        )

    @staticmethod
    def can_commit() -> bool:
        return False


__all__ = ["SandboxCommitBlocked", "SandboxPreparation", "SandboxToolPolicy"]
