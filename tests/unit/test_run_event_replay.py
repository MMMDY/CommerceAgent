"""Unit contracts for strict persisted run-event deserialization."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

import pytest

from src.protocols import EventType
from src.repositories.runs import EventReplayError, ReplayedRunEvent


def _hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(encoded.encode()).hexdigest()}"


def _row(payload: dict[str, Any] | str | list[object] | None = None) -> dict[str, Any]:
    safe_payload: dict[str, Any] | str | list[object]
    safe_payload = {"outcome": "ok"} if payload is None else payload
    hash_payload = safe_payload if isinstance(safe_payload, dict) else {"outcome": "ok"}
    return {
        "event_id": uuid4(),
        "run_id": uuid4(),
        "event_seq": 1,
        "event_type": "step_completed",
        "event_version": "1.0",
        "step_id": "observe",
        "payload_json": safe_payload,
        "payload_hash": _hash(hash_payload),
        "causation_id": None,
        "correlation_id": uuid4(),
        "created_at": datetime.now(UTC),
    }


def test_event_row_is_strictly_deserialized_without_exposing_raw_storage() -> None:
    row = _row({"outcome": "ok", "authorization": "[REDACTED]"})
    row["payload_hash"] = _hash(row["payload_json"])

    replayed = ReplayedRunEvent.from_persisted_row(row)

    assert replayed.sequence == 1
    assert replayed.event.event_type is EventType.STEP_COMPLETED
    assert replayed.event.payload == {"outcome": "ok", "authorization": "[REDACTED]"}
    assert replayed.payload_hash == row["payload_hash"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("event_version", "2.0", "unsupported persisted event version"),
        ("event_type", "invented_event", "domain event contract"),
        ("payload_hash", "sha256:" + "0" * 64, "payload hash mismatch"),
        ("created_at", datetime.now(), "timezone-aware"),
    ],
)
def test_invalid_event_metadata_fails_closed(field: str, value: object, message: str) -> None:
    row = _row()
    row[field] = value

    with pytest.raises(EventReplayError, match=message):
        ReplayedRunEvent.from_persisted_row(row)


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "provider-secret"},
        {"nested": {"confirmation_token": "one-time-token"}},
        {"customer": "13800138000"},
    ],
)
def test_unredacted_payload_never_crosses_replay_boundary(payload: dict[str, Any]) -> None:
    row = _row(payload)
    row["payload_hash"] = _hash(payload)

    with pytest.raises(EventReplayError, match="not redacted|unredacted PII"):
        ReplayedRunEvent.from_persisted_row(row)


def test_non_object_payload_is_rejected_before_domain_deserialization() -> None:
    with pytest.raises(EventReplayError, match="not an object"):
        ReplayedRunEvent.from_persisted_row(_row(["unsafe-shape"]))


def test_malformed_json_payload_is_rejected() -> None:
    with pytest.raises(EventReplayError, match="not valid JSON"):
        ReplayedRunEvent.from_persisted_row(_row("{"))
