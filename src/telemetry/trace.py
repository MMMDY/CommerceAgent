"""In-memory structured trace storage with mandatory data minimization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from re import sub
from typing import Any

_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "secret",
        "password",
        "confirmation_token",
        "chain_of_thought",
        "reasoning",
        "hidden_reasoning",
    }
)
_PHONE = r"(?<!\d)(?:\+?86[- ]?)?1\d{10}(?!\d)"
_MAX_TEXT = 512


@dataclass(frozen=True, slots=True)
class TraceRecord:
    sequence: int
    kind: str
    payload: dict[str, Any]
    payload_hash: str


class TraceStore:
    """Append-only trace retaining only safe, bounded structured observations."""

    def __init__(self) -> None:
        self._records: list[TraceRecord] = []

    def append(self, *, kind: str, payload: dict[str, Any]) -> TraceRecord:
        if not kind:
            raise ValueError("trace kind must not be empty")
        safe = _sanitize(payload)
        encoded = dumps(
            safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        record = TraceRecord(
            sequence=len(self._records) + 1,
            kind=kind,
            payload=safe,
            payload_hash=f"sha256:{sha256(encoded.encode()).hexdigest()}",
        )
        self._records.append(record)
        return record

    def records(self) -> tuple[TraceRecord, ...]:
        return tuple(deepcopy(self._records))


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in _FORBIDDEN_KEYS else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(item) for item in value)
    if isinstance(value, str):
        value = sub(_PHONE, "[PHONE_REDACTED]", value)
        return value[:_MAX_TEXT]
    return value
