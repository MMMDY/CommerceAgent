"""Owner-scoped catalog and order adapters for Phase 3 demos.

These fixtures intentionally model the boundary of a real business API: all
resource reads are filtered by the trusted actor on ``ToolContext`` and no
model-provided actor or tenant field is accepted.
"""

# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.protocols import ToolContext, ToolError, ToolErrorCode, ToolResult


@dataclass(frozen=True, slots=True)
class ProductFixture:
    sku: str
    title: str
    category: str
    price: float
    currency: str
    stock: int
    attributes: dict[str, str | int | float | bool]


@dataclass(frozen=True, slots=True)
class OrderFixture:
    order_id: str
    actor_id: str
    status: str
    item_skus: tuple[str, ...]
    tracking_id: str
    eta: str
    payment_status: str
    refund_status: str


DEFAULT_PRODUCTS: tuple[ProductFixture, ...] = (
    ProductFixture("BHD308/10", "ThermoProtect 吹风机", "hair-care", 199.0, "CNY", 12,
                   {"power_w": 1600, "heat_speeds": 3, "cold_air": True}),
    ProductFixture("BHD340/10", "ThermoProtect 护发吹风机", "hair-care", 269.0, "CNY", 8,
                   {"power_w": 2100, "heat_speeds": 6, "cold_air": True}),
    ProductFixture("TAH6206", "无线蓝牙耳机", "audio", 299.0, "CNY", 15,
                   {"bluetooth": "5.1", "battery_mah": 750, "usb_c": True}),
    ProductFixture("HD928X", "智能空气炸锅", "kitchen", 899.0, "CNY", 0,
                   {"dishwasher_safe": True, "keep_warm_minutes": 30}),
)

DEFAULT_ORDERS: tuple[OrderFixture, ...] = (
    OrderFixture("ORD-DEMO-001", "demo-user-001", "shipped", ("TAH6206",), "TRK-DEMO-001", "2026-09-16", "paid", "none"),
    OrderFixture("ORD-DEMO-002", "demo-user-001", "delivered", ("BHD308/10",), "TRK-DEMO-002", "2026-09-10", "paid", "none"),
    OrderFixture("ORD-DEMO-003", "demo-user-002", "processing", ("HD928X",), "TRK-DEMO-003", "2026-09-18", "paid", "none"),
)


def _success(name: str, data: dict[str, Any]) -> ToolResult:
    return ToolResult(tool_name=name, tool_version="1", data=data)


def _failure(name: str, code: ToolErrorCode = ToolErrorCode.RESOURCE_NOT_FOUND) -> ToolResult:
    return ToolResult(
        tool_name=name,
        tool_version="1",
        error=ToolError(code=code, retryable=False, message="未找到可访问的资源"),
    )


class MockReadOnlyAdapter:
    """Dispatch all Phase 3 readonly tool calls over immutable fixtures."""

    def __init__(
        self,
        *,
        products: tuple[ProductFixture, ...] = DEFAULT_PRODUCTS,
        orders: tuple[OrderFixture, ...] = DEFAULT_ORDERS,
    ) -> None:
        self._products = {item.sku: item for item in products}
        self._orders = {item.order_id: item for item in orders}

    def __call__(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        name = str(arguments.get("_tool_name", ""))
        handlers = {
            "search_catalog": self.search_catalog,
            "get_product_detail": self.get_product_detail,
            "compare_products": self.compare_products,
            "list_my_orders": self.list_my_orders,
            "get_order_status": self.get_order_status,
            "get_delivery_tracking": self.get_delivery_tracking,
            "get_payment_status": self.get_payment_status,
            "get_refund_status": self.get_refund_status,
        }
        handler = handlers.get(name)
        return handler(context, arguments) if handler else _failure(name, ToolErrorCode.INTERNAL_ERROR)

    def for_tool(self, name: str) -> Callable[[ToolContext, dict[str, object]], ToolResult]:
        """Return an adapter closure so tool identity is not a model argument."""
        handlers = {
            "search_catalog": self.search_catalog,
            "get_product_detail": self.get_product_detail,
            "compare_products": self.compare_products,
            "list_my_orders": self.list_my_orders,
            "get_order_status": self.get_order_status,
            "get_delivery_tracking": self.get_delivery_tracking,
            "get_payment_status": self.get_payment_status,
            "get_refund_status": self.get_refund_status,
        }
        try:
            handler = handlers[name]
        except KeyError as error:
            raise ValueError("unknown readonly fixture tool") from error
        return handler

    def search_catalog(self, _context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        query = str(arguments.get("query", "")).casefold()
        category = arguments.get("filters", {})
        category_value = category.get("category") if isinstance(category, dict) else None
        products = [
            self._product(item)
            for item in self._products.values()
            if (not query or query in f"{item.sku} {item.title} {item.category}".casefold())
            and (not category_value or item.category == category_value)
        ]
        raw_limit = arguments.get("limit", 10)
        limit = raw_limit if isinstance(raw_limit, int) and not isinstance(raw_limit, bool) else 10
        return _success("search_catalog", {"products": products[: max(1, min(limit, 20))]})

    def get_product_detail(self, _context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        product = self._products.get(str(arguments.get("product_id", arguments.get("sku", ""))))
        return _success("get_product_detail", {"product": self._product(product)}) if product else _failure("get_product_detail")

    def compare_products(self, _context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        identifiers = arguments.get("product_ids", arguments.get("skus", []))
        if not isinstance(identifiers, list) or not 2 <= len(identifiers) <= 4:
            return _failure("compare_products", ToolErrorCode.INVALID_ARGUMENT)
        products = [self._products.get(str(identifier)) for identifier in identifiers]
        if any(product is None for product in products):
            return _failure("compare_products")
        fields = arguments.get("fields", [])
        requested = [str(field) for field in fields] if isinstance(fields, list) and fields else ["price", "stock", "attributes"]
        return _success("compare_products", {"products": [
            {"sku": product.sku, **{field: self._product(product).get(field) for field in requested}}
            for product in products if product is not None
        ]})

    def list_my_orders(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        status = arguments.get("status")
        raw_limit = arguments.get("limit", 10)
        limit_value = raw_limit if isinstance(raw_limit, int) and not isinstance(raw_limit, bool) else 10
        limit = max(1, min(limit_value, 20))
        orders = [item for item in self._orders.values() if item.actor_id == context.actor_id and (not status or item.status == status)]
        return _success("list_my_orders", {"orders": [self._order(item) for item in orders[:limit]]})

    def get_order_status(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        order = self._owned_order(context, arguments)
        return _success("get_order_status", {"order": self._order(order)}) if order else _failure("get_order_status")

    def get_delivery_tracking(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        order = self._owned_order(context, arguments)
        if order is None:
            return _failure("get_delivery_tracking")
        return _success("get_delivery_tracking", {"tracking_id": order.tracking_id, "status": order.status, "eta": order.eta})

    def get_payment_status(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        order = self._owned_order(context, arguments)
        return _success("get_payment_status", {"order_id": order.order_id, "status": order.payment_status}) if order else _failure("get_payment_status")

    def get_refund_status(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        order = self._owned_order(context, arguments)
        return _success("get_refund_status", {"order_id": order.order_id, "status": order.refund_status}) if order else _failure("get_refund_status")

    def _owned_order(self, context: ToolContext, arguments: dict[str, object]) -> OrderFixture | None:
        order = self._orders.get(str(arguments.get("order_id", "")))
        return order if order is not None and order.actor_id == context.actor_id else None

    @staticmethod
    def _product(item: ProductFixture | None) -> dict[str, object]:
        if item is None:
            return {}
        return {"sku": item.sku, "title": item.title, "category": item.category, "price": item.price,
                "currency": item.currency, "stock": item.stock, "attributes": dict(item.attributes)}

    @staticmethod
    def _order(item: OrderFixture) -> dict[str, object]:
        return {"order_id": item.order_id, "status": item.status, "item_skus": list(item.item_skus),
                "tracking_id": item.tracking_id, "eta": item.eta, "payment_status": item.payment_status,
                "refund_status": item.refund_status}


class MockResourceAuthorizer:
    """Resource owner checker shared by ToolExecutor and the fixture adapter."""

    def __init__(self, orders: tuple[OrderFixture, ...] = DEFAULT_ORDERS) -> None:
        self._owners = {order.order_id: order.actor_id for order in orders}

    def authorize(self, *, owner_check: str, resource_id: object, context: ToolContext) -> bool:
        return owner_check == "order.owner" and self._owners.get(str(resource_id)) == context.actor_id
