"""Minimal Phase 0 conversation persistence repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, MetaData, String, Table, select
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

metadata = MetaData()

conversations = Table(
    "conversations",
    metadata,
    Column("id", PostgreSQLUUID(as_uuid=True), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("actor_id", String(128), nullable=False),
    Column("client_request_id", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    schema="conversation",
)


@dataclass(frozen=True, slots=True)
class Conversation:
    id: UUID
    tenant_id: str
    actor_id: str
    client_request_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class ConversationRepository:
    """Tenant-scoped conversation create/list methods."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_or_get(
        self, *, tenant_id: str, actor_id: str, client_request_id: str
    ) -> Conversation:
        now = datetime.now().astimezone()
        identifier = uuid4()
        statement = conversations.insert().values(
            id=identifier,
            tenant_id=tenant_id,
            actor_id=actor_id,
            client_request_id=client_request_id,
            status="active",
            created_at=now,
            updated_at=now,
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(statement)
        except IntegrityError:
            pass

        with self._engine.connect() as connection:
            row = connection.execute(
                select(conversations).where(
                    conversations.c.tenant_id == tenant_id,
                    conversations.c.actor_id == actor_id,
                    conversations.c.client_request_id == client_request_id,
                )
            ).one()
        return Conversation(**dict(row._mapping))

    def list_for_actor(self, *, tenant_id: str, actor_id: str) -> list[Conversation]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(conversations)
                .where(conversations.c.tenant_id == tenant_id, conversations.c.actor_id == actor_id)
                .order_by(conversations.c.updated_at.desc())
            ).all()
        return [Conversation(**dict(row._mapping)) for row in rows]
