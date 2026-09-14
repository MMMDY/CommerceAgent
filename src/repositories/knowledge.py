"""Tenant-filtered knowledge documents and evidence chunks."""

# ruff: noqa: E501

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.rag.models import Evidence


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    chunk_id: UUID
    document_id: UUID
    text: str
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class KnowledgeSearchRow:
    """Chunk plus document fields needed for deterministic ranking and citation."""

    chunk_id: UUID
    document_id: UUID
    chunk_no: int
    text: str
    metadata: dict[str, object]
    topic: str
    product_ref: str | None
    source_uri: str
    version: str


class KnowledgeRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add_document(self, *, tenant_id: str, topic: str, version: str, source_uri: str, content_hash: str,
                     effective_from: datetime, access_level: str = "customer",
                     product_ref: str | None = None, region: str | None = None,
                     effective_to: datetime | None = None, status: str = "active") -> UUID:
        document_id = uuid4()
        with self._engine.begin() as connection:
            connection.execute(text("INSERT INTO knowledge.knowledge_documents "
                "(document_id, tenant_id, topic, product_ref, region, version, effective_from, effective_to, "
                "access_level, source_uri, content_hash, status) VALUES (:document_id, :tenant_id, :topic, "
                ":product_ref, :region, :version, :effective_from, :effective_to, :access_level, :source_uri, "
                ":content_hash, :status)"), {"document_id": document_id, "tenant_id": tenant_id, "topic": topic,
                "product_ref": product_ref, "region": region, "version": version, "effective_from": effective_from,
                "effective_to": effective_to, "access_level": access_level, "source_uri": source_uri,
                "content_hash": content_hash, "status": status})
        return document_id

    def create_or_get_document(
        self, *, tenant_id: str, topic: str, product_ref: str | None, version: str,
        source_uri: str, content_hash: str,
    ) -> tuple[UUID, bool]:
        """Insert one source document or return the existing identical version."""
        with self._engine.begin() as connection:
            row = connection.execute(text(
                "SELECT document_id FROM knowledge.knowledge_documents "
                "WHERE tenant_id = :tenant_id AND source_uri = :source_uri AND version = :version"
            ), {"tenant_id": tenant_id, "source_uri": source_uri, "version": version}).first()
            if row is not None:
                return row[0], False
            document_id = uuid4()
            connection.execute(text(
                "INSERT INTO knowledge.knowledge_documents "
                "(document_id, tenant_id, topic, product_ref, version, effective_from, access_level, source_uri, "
                "content_hash, status) VALUES (:document_id, :tenant_id, :topic, :product_ref, :version, "
                ":effective_from, 'customer', :source_uri, :content_hash, 'active')"
            ), {"document_id": document_id, "tenant_id": tenant_id, "topic": topic,
                "product_ref": product_ref, "version": version, "effective_from": datetime.now().astimezone(),
                "source_uri": source_uri, "content_hash": content_hash})
            return document_id, True

    def create_chunk_if_absent(
        self, *, document_id: UUID, chunk_no: int, text_value: str, text_hash: str,
        index_version: str, metadata: dict[str, object] | None = None,
    ) -> bool:
        with self._engine.begin() as connection:
            inserted = connection.execute(text(
                "INSERT INTO knowledge.knowledge_chunks "
                "(chunk_id, document_id, chunk_no, text_redacted, text_hash, metadata_json, index_version, created_at) "
                "VALUES (:chunk_id, :document_id, :chunk_no, :text_value, :text_hash, CAST(:metadata AS jsonb), "
                ":index_version, now()) ON CONFLICT (document_id, chunk_no, index_version) DO NOTHING"
            ), {"chunk_id": uuid4(), "document_id": document_id, "chunk_no": chunk_no,
                "text_value": text_value, "text_hash": text_hash, "metadata": json.dumps(metadata or {}),
                "index_version": index_version})
            return inserted.rowcount == 1

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

    def search_active(
        self, *, tenant_id: str, access_level: str, query: str, topic: str | None = None,
        product_ref: str | None = None, limit: int = 30,
    ) -> list[KnowledgeSearchRow]:
        """Apply tenant/access/effective-time/status filters in SQL before ranking."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        clauses = [
            "d.tenant_id = :tenant_id", "d.access_level = :access_level", "d.status = 'active'",
            "d.effective_from <= now()", "(d.effective_to IS NULL OR d.effective_to > now())",
        ]
        params: dict[str, object] = {"tenant_id": tenant_id, "access_level": access_level, "query": query, "limit": limit}
        if topic is not None:
            clauses.append("d.topic = :topic")
            params["topic"] = topic
        if product_ref is not None:
            clauses.append("(d.product_ref = :product_ref OR d.product_ref IS NULL)")
            params["product_ref"] = product_ref
        with self._engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT c.chunk_id, c.document_id, c.chunk_no, c.text_redacted, c.metadata_json, d.topic, "
                "d.product_ref, d.source_uri, d.version FROM knowledge.knowledge_chunks c "
                "JOIN knowledge.knowledge_documents d ON d.document_id = c.document_id WHERE "
                + " AND ".join(clauses)
                + " ORDER BY similarity(c.text_redacted, :query) DESC, c.chunk_no LIMIT :limit"
            ), params).all()
        return [KnowledgeSearchRow(*tuple(row)) for row in rows]

    def evidence_for_ids(
        self, *, tenant_id: str, access_level: str, evidence_ids: tuple[str, ...]
    ) -> tuple[Evidence, ...]:
        """Resolve opaque evidence IDs through the same tenant/access boundary."""
        resolved: list[Evidence] = []
        for evidence_id in evidence_ids:
            parts = evidence_id.split(":")
            if len(parts) != 3 or parts[0] != "knowledge":
                continue
            try:
                document_id, chunk_id = UUID(parts[1]), UUID(parts[2])
            except ValueError:
                continue
            with self._engine.connect() as connection:
                row = connection.execute(text(
                    "SELECT c.chunk_id, c.text_redacted, d.source_uri, d.version FROM knowledge.knowledge_chunks c "
                    "JOIN knowledge.knowledge_documents d ON d.document_id = c.document_id "
                    "WHERE c.chunk_id = :chunk_id AND d.document_id = :document_id "
                    "AND d.tenant_id = :tenant_id AND d.access_level = :access_level "
                    "AND d.status = 'active' AND d.effective_from <= now() "
                    "AND (d.effective_to IS NULL OR d.effective_to > now())"
                ), {"chunk_id": chunk_id, "document_id": document_id, "tenant_id": tenant_id,
                    "access_level": access_level}).first()
            if row is not None:
                resolved.append(Evidence(
                    evidence_id=evidence_id,
                    document_id=str(document_id),
                    source_uri=row[2],
                    version=row[3],
                    excerpt=row[1][:1200],
                    score=0.0,
                ))
        return tuple(resolved)
