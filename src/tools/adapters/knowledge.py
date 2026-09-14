"""PostgreSQL-backed retrieval adapter with mandatory tenant/access filters."""

# ruff: noqa: E501

from __future__ import annotations

from src.protocols import ToolContext, ToolError, ToolErrorCode, ToolResult
from src.rag.retrieval import KnowledgeRetriever
from src.repositories.knowledge import KnowledgeRepository


class KnowledgeToolAdapter:
    """Convert trusted runtime context into an evidence-only tool result."""

    def __init__(self, repository: KnowledgeRepository, retriever: KnowledgeRetriever | None = None) -> None:
        self._repository = repository
        self._retriever = retriever or KnowledgeRetriever()

    def __call__(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(
                tool_name="retrieve_knowledge", tool_version="1",
                error=ToolError(code=ToolErrorCode.INVALID_ARGUMENT, retryable=False, message="查询内容无效"),
            )
        metadata = arguments.get("metadata_filter", {})
        if not isinstance(metadata, dict) or set(metadata).difference({"topic", "product_ref"}):
            return ToolResult(
                tool_name="retrieve_knowledge", tool_version="1",
                error=ToolError(code=ToolErrorCode.INVALID_ARGUMENT, retryable=False, message="检索过滤条件无效"),
            )
        top_k_value = arguments.get("top_k", 3)
        top_k = top_k_value if isinstance(top_k_value, int) and not isinstance(top_k_value, bool) else 3
        try:
            rows = self._repository.search_active(
                tenant_id=context.tenant_id, access_level="customer", query=query,
                topic=metadata.get("topic") if isinstance(metadata.get("topic"), str) else None,
                product_ref=metadata.get("product_ref") if isinstance(metadata.get("product_ref"), str) else None,
            )
            pack = self._retriever.build_pack(query=query, rows=rows, top_k=top_k)
        except ValueError:
            return ToolResult(
                tool_name="retrieve_knowledge", tool_version="1",
                error=ToolError(code=ToolErrorCode.INVALID_ARGUMENT, retryable=False, message="检索参数无效"),
            )
        return ToolResult(
            tool_name="retrieve_knowledge", tool_version="1",
            data={"evidence_ids": list(pack.evidence_ids), "evidence": [item.model_dump() for item in pack.evidence]},
        )
