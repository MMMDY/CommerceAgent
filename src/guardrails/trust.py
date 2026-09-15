"""Explicit markers for data that must never expand execution authority.

The marker is intentionally a small immutable value object rather than a
magic prompt string.  Callers can pass its ``text`` to a model while retaining
the trust level in structured state and logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.telemetry.trace import _sanitize


class TrustLevel(StrEnum):
    USER = "untrusted_user"
    RAG = "untrusted_rag"
    TOOL = "untrusted_tool_result"
    SYSTEM = "trusted_system"


@dataclass(frozen=True, slots=True)
class UntrustedValue:
    text: str
    source: TrustLevel

    def as_prompt_block(self) -> str:
        """Serialize with an explicit non-instruction boundary."""

        return f'<untrusted source="{self.source.value}">{self.text}</untrusted>'


def mark_untrusted(value: Any, source: TrustLevel) -> UntrustedValue:
    if isinstance(value, str):
        text = value
    else:
        text = str(value)
    return UntrustedValue(text=_sanitize(text), source=source)


def sanitize(value: Any) -> Any:
    """Public redaction entry point for report/log/audit boundaries."""

    return _sanitize(value)
