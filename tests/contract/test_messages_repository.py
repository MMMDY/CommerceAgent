"""PostgreSQL contracts for conversation message ordering and idempotency."""

# ruff: noqa: E501

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from src.repositories.messages import MessageConflictError, MessageRepository


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = os.environ.get("DATABASE_TEST_URL")
    if url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(url, pool_pre_ping=True)


def conversation(engine: Engine, actor: str) -> tuple[str, object]:
    tenant = f"messages-{uuid4()}"
    identifier = uuid4()
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO conversation.conversations "
            "(id, tenant_id, actor_id, client_request_id, status, created_at, updated_at) "
            "VALUES (:id, :tenant, :actor, :request, 'active', :now, :now)"
        ), {"id": identifier, "tenant": tenant, "actor": actor, "request": str(uuid4()), "now": now})
    return tenant, identifier


def test_user_message_is_idempotent_and_sequence_is_strict(engine: Engine) -> None:
    tenant, conversation_id = conversation(engine, "actor-a")
    repository = MessageRepository(engine)
    first = repository.append_user(
        conversation_id=conversation_id, tenant_id=tenant, actor_id="actor-a",
        content="查询订单", client_message_id="client-1", run_id=uuid4(),
    )
    same = repository.append_user(
        conversation_id=conversation_id, tenant_id=tenant, actor_id="actor-a",
        content="查询订单", client_message_id="client-1", run_id=uuid4(),
    )
    assert same.message_id == first.message_id
    assert same.run_id == first.run_id
    with pytest.raises(MessageConflictError):
        repository.append_user(
            conversation_id=conversation_id, tenant_id=tenant, actor_id="actor-a",
            content="查询另一个订单", client_message_id="client-1",
        )
    assistant = repository.append_assistant(
        conversation_id=conversation_id, tenant_id=tenant, actor_id="actor-a", content="请提供订单号",
    )
    assert (first.sequence_no, assistant.sequence_no) == (1, 2)
    assert [item.sequence_no for item in repository.list_for_actor(
        conversation_id=conversation_id, tenant_id=tenant, actor_id="actor-a"
    )] == [1, 2]


def test_messages_are_not_visible_to_another_actor_or_tenant(engine: Engine) -> None:
    tenant, conversation_id = conversation(engine, "actor-a")
    repository = MessageRepository(engine)
    repository.append_user(
        conversation_id=conversation_id, tenant_id=tenant, actor_id="actor-a",
        content="只属于 actor-a", client_message_id="client-owner",
    )
    assert repository.list_for_actor(
        conversation_id=conversation_id, tenant_id=tenant, actor_id="actor-b"
    ) == ()
    assert repository.list_for_actor(
        conversation_id=conversation_id, tenant_id="other-tenant", actor_id="actor-a"
    ) == ()
