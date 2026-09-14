"""Versioned model-visible readonly tool specifications for Phase 3."""

# ruff: noqa: E501

from __future__ import annotations

from src.protocols import ResourceBinding, RetryPolicy, ToolRisk, ToolSpec

_RETRY = RetryPolicy(max_attempts=2, backoff_ms=(100,))
_STRING = {"type": "string"}


def _spec(
    name: str, properties: dict[str, object], required: list[str], output_required: list[str],
    scope: str, *, resource: str | None = None,
) -> ToolSpec:
    return ToolSpec(
        name=name, version="1",
        input_schema={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        output_schema={"type": "object", "properties": {key: {} for key in output_required},
                       "required": output_required, "additionalProperties": False},
        risk=ToolRisk.READ_ONLY, required_scopes=(scope,), timeout_ms=3_000,
        retry_policy=_RETRY, model_visible=True,
        resource_binding=ResourceBinding(argument=resource, owner_check="order.owner") if resource else None,
    )


def readonly_tool_specs() -> tuple[ToolSpec, ...]:
    """Return a fresh immutable tuple to keep registry definitions unmodifiable."""
    return (
        _spec("search_catalog", {"query": _STRING, "filters": {"type": "object"}, "limit": {"type": "integer"}}, ["query"], ["products"], "catalog:read"),
        _spec("get_product_detail", {"product_id": _STRING}, ["product_id"], ["product"], "catalog:read"),
        _spec("compare_products", {"product_ids": {"type": "array"}, "fields": {"type": "array"}}, ["product_ids"], ["products"], "catalog:read"),
        _spec(
            "retrieve_knowledge",
            {"query": _STRING, "metadata_filter": {"type": "object"}, "top_k": {"type": "integer"}},
            ["query"], ["evidence_ids", "evidence"], "knowledge:read",
        ),
        _spec("list_my_orders", {"status": _STRING, "time_range": _STRING, "limit": {"type": "integer"}}, [], ["orders"], "order:read"),
        _spec("get_order_status", {"order_id": _STRING}, ["order_id"], ["order"], "order:read", resource="order_id"),
        _spec("get_delivery_tracking", {"order_id": _STRING, "tracking_id": _STRING}, ["order_id"], ["tracking_id", "status", "eta"], "delivery:read", resource="order_id"),
        _spec("get_payment_status", {"order_id": _STRING}, ["order_id"], ["order_id", "status"], "payment:read", resource="order_id"),
        _spec("get_refund_status", {"order_id": _STRING, "refund_id": _STRING}, [], ["order_id", "status"], "refund:read", resource="order_id"),
    )
