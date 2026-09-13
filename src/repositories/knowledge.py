"""Tenant-filtered knowledge documents and evidence chunks."""

# ruff: noqa: E501

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    chunk_id: UUID
    document_id: UUID
    text: str
    metadata: dict[str, object]


class KnowledgeRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add_document(self, *, tenant_id: str, topic: str, version: str, source_uri: str, content_hash: str,
                     effective_from: datetime, access_level: str = "customer") -> UUID:
        document_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(text("INSERT INTO knowledge.knowledge_documents "
                "(document_id, tenant_id, topic, version, effective_from, access_level, source_uri, content_hash, status) "
                "VALUES (:document_id, :tenant_id, :topic, :version, :effective_from, :access_level, :source_uri, "
                ":content_hash, 'active')"), {"document_id": document_id, "tenant_id": tenant_id, "topic": topic,
                "version": version, "effective_from": effective_from, "access_level": access_level,
                "source_uri": source_uri, "content_hash": content_hash})
        return document_id

    def add_chunk(self, *, document_id: UUID, chunk_no: int, text_value: str, text_hash: str,
                  index_version: str, metadata: dict[str, object] | None = None) -> UUID:
        chunk_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(text("INSERT INTO knowledge.knowledge_chunks "
                "(chunk_id, document_id, chunk_no, text_redacted, text_hash, metadata_json, index_version, created_at) "
                "VALUES (:chunk_id, :document_id, :chunk_no, :text_value, :text_hash, CAST(:metadata AS jsonb), "
                ":index_version, now())"), {"chunk_id": chunk_id, "document_id": document_id, "chunk_no": chunk_no,
                "text_value": text_value, "text_hash": text_hash, "metadata": json.dumps(metadata or {}),
                "index_version": index_version})
        return chunk_id

    def active_chunks(self, *, tenant_id: str, topic: str, access_level: str) -> list[KnowledgeChunk]:
        with self._engine.connect() as connection:
            rows = connection.execute(text("SELECT c.chunk_id, c.document_id, c.text_redacted, c.metadata_json "
                "FROM knowledge.knowledge_chunks c JOIN knowledge.knowledge_documents d ON d.document_id = c.document_id "
                "WHERE d.tenant_id = :tenant_id AND d.topic = :topic AND d.access_level = :access_level "
                "AND d.status = 'active' AND d.effective_from <= now() "
                "AND (d.effective_to IS NULL OR d.effective_to > now()) ORDER BY c.chunk_no"),
                {"tenant_id": tenant_id, "topic": topic, "access_level": access_level}).all()
        return [KnowledgeChunk(*tuple(row)) for row in rows]
