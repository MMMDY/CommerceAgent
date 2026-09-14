from uuid import uuid4

import pytest

from src.rag.models import EvidencePack
from src.rag.retrieval import KnowledgeRetriever, lexical_terms
from src.repositories.knowledge import KnowledgeSearchRow


def row(text: str, *, topic: str = "policy", product_ref: str | None = None) -> KnowledgeSearchRow:
    identifier = uuid4()
    return KnowledgeSearchRow(
        chunk_id=uuid4(), document_id=identifier, chunk_no=0, text=text,
        metadata={}, topic=topic, product_ref=product_ref,
        source_uri=f"manual://{identifier}", version="v1",
    )


def test_lexical_terms_normalizes_latin_and_emits_cjk_ngrams() -> None:
    terms = lexical_terms(" Bluetooth 5.1 ")
    assert "bluetooth" in terms
    assert "5" in terms
    assert "蓝牙" not in lexical_terms("蓝")  # a one-character query has no 2/3-gram
    assert "蓝牙" in lexical_terms("支持蓝牙")


def test_retriever_ranks_matching_rows_and_returns_citations() -> None:
    matching = row(
        "支持 Bluetooth 5.1，并通过 USB-C 充电。",
        topic="Technical data", product_ref="TAH6206",
    )
    unrelated = row("可放入洗碗机清洗。", topic="Cleaning", product_ref="HD928X")
    pack = KnowledgeRetriever().build_pack(
        query="TAH6206 支持什么蓝牙版本？", rows=[unrelated, matching]
    )
    assert isinstance(pack, EvidencePack)
    assert pack.evidence_ids == (f"knowledge:{matching.document_id}:{matching.chunk_id}",)
    assert pack.evidence[0].source_uri.startswith("manual://")


def test_retriever_is_bounded_and_rejects_invalid_top_k() -> None:
    with pytest.raises(ValueError):
        KnowledgeRetriever().build_pack(query="退款", rows=[], top_k=0)
    pack = KnowledgeRetriever().build_pack(query="不存在", rows=[row("退款政策")])
    assert pack.evidence == ()
    assert pack.is_sufficient is False
