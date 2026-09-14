"""Deterministic JSONL knowledge ingestion with an auditable content version."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from src.repositories.knowledge import KnowledgeRepository


@dataclass(frozen=True, slots=True)
class IngestionResult:
    source_hash: str
    version: str
    documents: int
    chunks: int


def ingest_jsonl(*, repository: KnowledgeRepository, path: Path, tenant_id: str) -> IngestionResult:
    """Load the checked-in knowledge corpus in file order.

    Re-ingesting the same bytes is idempotent through the repository's source hash
    lookup.  The source data is deliberately not rewritten or model-summarised.
    """

    raw = path.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    version = f"static-{source_hash[:12]}"
    documents = chunks = 0
    for line_number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        required = ("id", "section", "text")
        if not all(isinstance(item.get(key), str) and item[key].strip() for key in required):
            raise ValueError(f"knowledge line {line_number} is missing required text fields")
        source_uri = str(item["id"])
        content = str(item["text"])
        document_id, created = repository.create_or_get_document(
            tenant_id=tenant_id,
            topic=str(item["section"]),
            product_ref=str(item.get("product") or "") or None,
            version=version,
            source_uri=source_uri,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        if created:
            documents += 1
        if repository.create_chunk_if_absent(
            document_id=document_id,
            chunk_no=0,
            text_value=content,
            text_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            index_version=version,
            metadata={
                "dataset": str(item.get("dataset") or ""),
                "product": str(item.get("product") or ""),
            },
        ):
            chunks += 1
    return IngestionResult(
        source_hash=source_hash, version=version, documents=documents, chunks=chunks
    )
