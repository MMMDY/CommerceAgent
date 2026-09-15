"""Tenant-scoped conversation message persistence and idempotency."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.telemetry.trace import _sanitize


class MessageConflictError(ValueError):
    """A client message id was reused with different content."""


@dataclass(frozen=True, slots=True)
class MessageRecord:
    message_id: UUID
    conversation_id: UUID
    run_id: UUID | None
    client_message_id: str | None
    role: str
    content_redacted: str
    content_hash: str
    sequence_no: int
    created_at: datetime
    created: bool = False


class MessageRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append_user(
        self, *, conversation_id: UUID, tenant_id: str, actor_id: str, content: str,
        client_message_id: str, run_id: UUID | None = None,
    ) -> MessageRecord:
        if not content.strip() or len(content) > 8000:
            raise ValueError("message content is invalid")
        if not client_message_id or len(client_message_id) > 128:
            raise ValueError("client_message_id is invalid")
        content_hash = f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
        content_redacted = str(_sanitize(content))
        with self._engine.begin() as connection:
            existing = connection.execute(text(
                "SELECT m.message_id, m.conversation_id, m.run_id, m.client_message_id, m.role, "
                "m.content_redacted, m.content_hash, m.sequence_no, m.created_at "
                "FROM conversation.messages m JOIN conversation.conversations c "
                "ON c.id = m.conversation_id WHERE m.conversation_id = :conversation_id "
                "AND c.tenant_id = :tenant_id AND c.actor_id = :actor_id "
                "AND m.client_message_id = :client_message_id"
            ), {"conversation_id": conversation_id, "tenant_id": tenant_id, "actor_id": actor_id,
                "client_message_id": client_message_id}).first()
            if existing is not None:
                record = MessageRecord(**dict(existing._mapping))
                if record.content_hash != content_hash:
                    raise MessageConflictError("client_message_id was reused with different content")
                return record
            conversation = connection.execute(text(
                "SELECT id FROM conversation.conversations WHERE id = :conversation_id "
                "AND tenant_id = :tenant_id AND actor_id = :actor_id FOR UPDATE"
            ), {"conversation_id": conversation_id, "tenant_id": tenant_id, "actor_id": actor_id}).first()
            if conversation is None:
                raise ValueError("conversation is unavailable for this tenant and actor")
            sequence = connection.execute(text(
                "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM conversation.messages "
                "WHERE conversation_id = :conversation_id"
            ), {"conversation_id": conversation_id}).scalar_one()
            now = datetime.now(UTC)
            message_id = uuid4()
            connection.execute(text(
                "INSERT INTO conversation.messages (message_id, conversation_id, run_id, client_message_id, role, "
                "content_redacted, content_hash, pii_labels_json, sequence_no, created_at) VALUES "
                "(:message_id, :conversation_id, :run_id, :client_message_id, 'user', :content, :content_hash, "
                "'{}'::jsonb, :sequence_no, :created_at)"
            ), {"message_id": message_id, "conversation_id": conversation_id, "run_id": run_id,
                "client_message_id": client_message_id, "content": content_redacted, "content_hash": content_hash,
                "sequence_no": sequence, "created_at": now})
            connection.execute(text(
                "UPDATE conversation.conversations SET updated_at = :updated_at WHERE id = :conversation_id"
            ), {"updated_at": now, "conversation_id": conversation_id})
            return MessageRecord(message_id, conversation_id, run_id, client_message_id, "user", content_redacted,
                                 content_hash, int(sequence), now, True)

    def append_assistant(
        self, *, conversation_id: UUID, tenant_id: str, actor_id: str, content: str,
        run_id: UUID | None = None,
    ) -> MessageRecord:
        if not content.strip() or len(content) > 8000:
            raise ValueError("message content is invalid")
        content_redacted = str(_sanitize(content))
        with self._engine.begin() as connection:
            conversation = connection.execute(text(
                "SELECT id FROM conversation.conversations WHERE id = :conversation_id "
                "AND tenant_id = :tenant_id AND actor_id = :actor_id FOR UPDATE"
            ), {"conversation_id": conversation_id, "tenant_id": tenant_id, "actor_id": actor_id}).first()
            if conversation is None:
                raise ValueError("conversation is unavailable for this tenant and actor")
            sequence = connection.execute(text(
                "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM conversation.messages WHERE conversation_id = :conversation_id"
            ), {"conversation_id": conversation_id}).scalar_one()
            now = datetime.now(UTC)
            message_id = uuid4()
            content_hash = f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
            connection.execute(text(
                "INSERT INTO conversation.messages (message_id, conversation_id, run_id, client_message_id, role, "
                "content_redacted, content_hash, pii_labels_json, sequence_no, created_at) VALUES "
                "(:message_id, :conversation_id, :run_id, NULL, 'assistant', :content, :content_hash, '{}'::jsonb, "
                ":sequence_no, :created_at)"
            ), {"message_id": message_id, "conversation_id": conversation_id, "run_id": run_id,
                "content": content_redacted, "content_hash": content_hash, "sequence_no": sequence, "created_at": now})
            connection.execute(text(
                "UPDATE conversation.conversations SET updated_at = :updated_at WHERE id = :conversation_id"
            ), {"updated_at": now, "conversation_id": conversation_id})
            return MessageRecord(message_id, conversation_id, run_id, None, "assistant", content_redacted,
                                 content_hash, int(sequence), now, True)

    def find_user_by_client_message_id(
        self,
        *,
        conversation_id: UUID,
        tenant_id: str,
        actor_id: str,
        client_message_id: str,
    ) -> MessageRecord | None:
        """Read an idempotent user message before creating a new Run."""

        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT m.message_id, m.conversation_id, m.run_id, m.client_message_id, m.role, "
                    "m.content_redacted, m.content_hash, m.sequence_no, m.created_at "
                    "FROM conversation.messages AS m JOIN conversation.conversations AS c "
                    "ON c.id = m.conversation_id WHERE m.conversation_id = :conversation_id "
                    "AND c.tenant_id = :tenant_id AND c.actor_id = :actor_id "
                    "AND m.client_message_id = :client_message_id"
                ),
                {
                    "conversation_id": conversation_id,
                    "tenant_id": tenant_id,
                    "actor_id": actor_id,
                    "client_message_id": client_message_id,
                },
            ).first()
        return MessageRecord(**dict(row._mapping), created=False) if row is not None else None

    def conversation_exists(
        self, *, conversation_id: UUID, tenant_id: str, actor_id: str
    ) -> bool:
        with self._engine.connect() as connection:
            return (
                connection.execute(
                    text(
                        "SELECT 1 FROM conversation.conversations WHERE id = :conversation_id "
                        "AND tenant_id = :tenant_id AND actor_id = :actor_id"
                    ),
                    {
                        "conversation_id": conversation_id,
                        "tenant_id": tenant_id,
                        "actor_id": actor_id,
                    },
                ).first()
                is not None
            )

    def list_for_actor(
        self, *, conversation_id: UUID, tenant_id: str, actor_id: str, after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[MessageRecord, ...]:
        if not 0 <= after_sequence or not 1 <= limit <= 500:
            raise ValueError("message cursor or limit is invalid")
        with self._engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT m.message_id, m.conversation_id, m.run_id, m.client_message_id, m.role, "
                "m.content_redacted, m.content_hash, m.sequence_no, m.created_at "
                "FROM conversation.messages m JOIN conversation.conversations c ON c.id = m.conversation_id "
                "WHERE m.conversation_id = :conversation_id AND c.tenant_id = :tenant_id AND c.actor_id = :actor_id "
                "AND m.sequence_no > :after_sequence ORDER BY m.sequence_no LIMIT :limit"
            ), {"conversation_id": conversation_id, "tenant_id": tenant_id, "actor_id": actor_id,
                "after_sequence": after_sequence, "limit": limit}).all()
        return tuple(MessageRecord(**dict(row._mapping)) for row in rows)
