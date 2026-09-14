from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.memory.session import build_session_memory
from src.repositories.memory import MemoryRepository, MemoryValidationError
from src.repositories.messages import MessageRecord
from src.repositories.runs import RunSnapshot


def _message(role: str, content: str) -> MessageRecord:
    return MessageRecord(
        message_id=uuid4(),
        conversation_id=uuid4(),
        run_id=None,
        client_message_id=None,
        role=role,
        content_redacted=content,
        content_hash="sha256:test",
        sequence_no=1,
        created_at=datetime.now(UTC),
    )


def test_session_memory_uses_only_redacted_conversation_and_run_metadata() -> None:
    run = RunSnapshot(
        run_id=uuid4(), tenant_id="demo", status="waiting_user", current_step="retrieve",
        row_version=1, last_checkpoint_seq=1, step_count=1,
    )
    memory = build_session_memory(
        messages=(_message("assistant", "旧回复"), _message("user", "查订单")), run=run
    )
    assert memory["latest_user_goal"] == "查订单"
    assert memory["workflow"] == {
        "run_id": str(run.run_id),
        "status": "waiting_user",
        "current_step": "retrieve",
        "step_count": 1,
    }
    assert memory["evidence_ids"] == []


def test_long_term_memory_rejects_dynamic_or_inferred_data_before_database_access() -> None:
    with pytest.raises(MemoryValidationError):
        MemoryRepository._validate_write(
            fact_type="order_status", source_type="user", confidence=1.0, value={"value": "shipped"}
        )
    with pytest.raises(MemoryValidationError):
        MemoryRepository._validate_write(
            fact_type="preferred_color",
            source_type="model",
            confidence=1.0,
            value={"value": "blue"},
        )
    MemoryRepository._validate_write(
        fact_type="preferred_color", source_type="user", confidence=1.0, value={"value": "blue"}
    )
