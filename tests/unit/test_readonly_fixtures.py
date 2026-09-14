"""Security contracts for fixed readonly business fixtures."""

# ruff: noqa: E501

from uuid import uuid4

from src.protocols import ToolContext
from src.tools.adapters.mock.read_only import MockReadOnlyAdapter, MockResourceAuthorizer


def context(actor: str = "demo-user-001") -> ToolContext:
    return ToolContext(
        request_id=uuid4(), run_id=uuid4(), conversation_id=uuid4(), tenant_id="demo-tenant",
        actor_id=actor, scopes=("catalog:read", "order:read", "delivery:read", "payment:read", "refund:read"),
        workflow_id="catalog_query", workflow_version="1", current_step="retrieve", policy_version="phase3",
    )


def test_catalog_detail_and_compare_are_structured_and_side_effect_free() -> None:
    adapter = MockReadOnlyAdapter()
    detail = adapter.get_product_detail(context(), {"product_id": "TAH6206"})
    assert detail.error is None
    assert detail.data and detail.data["product"]["sku"] == "TAH6206"
    comparison = adapter.compare_products(
        context(), {"product_ids": ["BHD308/10", "BHD340/10"], "fields": ["price", "stock"]}
    )
    assert comparison.error is None
    assert comparison.data and len(comparison.data["products"]) == 2


def test_order_reads_are_owner_scoped_even_if_another_order_id_is_supplied() -> None:
    adapter = MockReadOnlyAdapter()
    allowed = adapter.get_order_status(context("demo-user-001"), {"order_id": "ORD-DEMO-001"})
    denied = adapter.get_order_status(context("demo-user-001"), {"order_id": "ORD-DEMO-003"})
    assert allowed.error is None
    assert denied.error is not None
    assert MockResourceAuthorizer().authorize(
        owner_check="order.owner", resource_id="ORD-DEMO-003", context=context("demo-user-001")
    ) is False


def test_list_orders_never_leaks_orders_from_other_actor() -> None:
    adapter = MockReadOnlyAdapter()
    result = adapter.list_my_orders(context("demo-user-002"), {})
    assert result.error is None
    assert result.data and [order["order_id"] for order in result.data["orders"]] == ["ORD-DEMO-003"]
