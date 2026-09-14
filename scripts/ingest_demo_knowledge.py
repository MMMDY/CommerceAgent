"""Idempotently seed the checked-in Phase 3 demo knowledge corpus."""

from __future__ import annotations

from pathlib import Path

from src.db import get_engine
from src.rag.ingestion import ingest_jsonl
from src.repositories.knowledge import KnowledgeRepository


def main() -> int:
    result = ingest_jsonl(
        repository=KnowledgeRepository(get_engine()),
        path=Path("evals/commerce_bench_zh/knowledge.jsonl"),
        tenant_id="demo-tenant",
    )
    print(f"demo knowledge ingested: documents={result.documents} chunks={result.chunks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
