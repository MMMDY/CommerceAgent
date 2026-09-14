"""Small deterministic lexical retriever used before any dense index is introduced."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from src.rag.models import Evidence, EvidencePack
from src.repositories.knowledge import KnowledgeSearchRow

_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def lexical_terms(value: str) -> frozenset[str]:
    """Return latin words plus Unicode 2/3-grams for deterministic CJK matching."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    words = set(_WORD.findall(normalized))
    compact = "".join(character for character in normalized if not character.isspace())
    for width in (2, 3):
        words.update(compact[index : index + width] for index in range(len(compact) - width + 1))
    return frozenset(term for term in words if term)


class KnowledgeRetriever:
    """Ranks pre-filtered chunks in application code and returns citeable evidence."""

    def build_pack(
        self, *, query: str, rows: Iterable[KnowledgeSearchRow], top_k: int = 3
    ) -> EvidencePack:
        if not 1 <= top_k <= 5:
            raise ValueError("top_k must be between 1 and 5")
        query_terms = lexical_terms(query)
        ranked: list[tuple[float, KnowledgeSearchRow]] = []
        for row in rows:
            row_terms = lexical_terms(f"{row.text} {row.topic} {row.product_ref or ''}")
            overlap = len(query_terms.intersection(row_terms))
            if overlap:
                # Product identifiers and exact word terms have already contributed
                # through the same stable term set; no model-derived reranking occurs.
                ranked.append((overlap / max(1, len(query_terms)), row))
        ranked.sort(key=lambda item: (-item[0], item[1].source_uri, item[1].chunk_no))
        return EvidencePack(
            query=query,
            evidence=tuple(
                Evidence(
                    evidence_id=f"knowledge:{row.document_id}:{row.chunk_id}",
                    document_id=str(row.document_id),
                    source_uri=row.source_uri,
                    version=row.version,
                    excerpt=row.text[:1200],
                    score=score,
                )
                for score, row in ranked[:top_k]
            ),
        )
