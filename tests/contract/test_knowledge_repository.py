"""PostgreSQL contracts for tenant-filtered RAG evidence."""

# ruff: noqa: E501

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine

from src.repositories.knowledge import KnowledgeRepository


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = os.environ.get("DATABASE_TEST_URL")
    if url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(url, pool_pre_ping=True)


def test_chunks_are_visible_only_through_active_tenant_document(engine: Engine) -> None:
    repository = KnowledgeRepository(engine)
    tenant_id = f"knowledge-{uuid4()}"
    document_id = repository.add_document(tenant_id=tenant_id, topic="refund", version="1", source_uri="fixture", content_hash="hash", effective_from=datetime.now(UTC))
    repository.add_chunk(document_id=document_id, chunk_no=0, text_value="退款政策", text_hash="text", index_version="1")
    chunks = repository.active_chunks(tenant_id=tenant_id, topic="refund", access_level="customer")
    assert [chunk.text for chunk in chunks] == ["退款政策"]
    assert repository.active_chunks(tenant_id=f"other-{tenant_id}", topic="refund", access_level="customer") == []
