"""Unit contracts for evidence adapter filtering."""

# ruff: noqa: E501

from uuid import uuid4

from src.protocols import ToolContext
from src.rag.retrieval import KnowledgeRetriever
from src.repositories.knowledge import KnowledgeSearchRow
from src.tools.adapters.knowledge import KnowledgeToolAdapter


class FakeKnowledgeRepository:
    def __init__(self, rows: list[KnowledgeSearchRow]) -> None:
        self.rows = rows
        self.received: dict[str, object] = {}

    def search_active(self, **kwargs: object) -> list[KnowledgeSearchRow]:
        self.received = kwargs
        return self.rows


def _context() -> ToolContext:
    return ToolContext(
        request_id=uuid4(), run_id=uuid4(), conversation_id=uuid4(), tenant_id="tenant-a",
        actor_id="actor-a", scopes=("knowledge:read",), workflow_id="knowledge_query",
        workflow_version="1", current_step="retrieve", policy_version="v1",
    )


def test_knowledge_adapter_returns_evidence_and_forces_tenant_filter() -> None:
    document_id, chunk_id = uuid4(), uuid4()
    repository = FakeKnowledgeRepository([
        KnowledgeSearchRow(chunk_id, document_id, 0, "退款政策：签收后七天内可申请。", {}, "refund", None, "manual://refund", "v1")
    ])
    result = KnowledgeToolAdapter(repository, KnowledgeRetriever())(
        _context(), {"query": "退款政策", "metadata_filter": {"topic": "refund"}}
    )
    assert result.error is None
    assert result.data and result.data["evidence_ids"]
    assert repository.received["tenant_id"] == "tenant-a"
    assert repository.received["access_level"] == "customer"


def test_knowledge_adapter_rejects_unapproved_metadata_filters() -> None:
    repository = FakeKnowledgeRepository([])
    result = KnowledgeToolAdapter(repository)(
        _context(), {"query": "退款", "metadata_filter": {"tenant_id": "other"}}
    )
    assert result.error is not None
    assert repository.received == {}
