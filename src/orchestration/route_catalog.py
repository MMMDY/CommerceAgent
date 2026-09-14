"""Code-owned Phase 3 intent map and slot requirements.

The classifier can suggest an intent, but these tables alone decide whether an
executor is eligible.  Unknown intents remain handoff by ``IntentRouter``.
"""

from __future__ import annotations

from src.orchestration.router import IntentRouteRule
from src.protocols import ExecutionMode

_READONLY = ExecutionMode.READONLY_LOOP
_WORKFLOW = ExecutionMode.WORKFLOW

# The route labels are stable API/evaluation identifiers.  Write routes are
# declared now so Phase 4 can publish their deterministic workflow versions.
DEFAULT_INTENT_ROUTE_RULES: tuple[IntentRouteRule, ...] = tuple(
    IntentRouteRule(intent, mode, route, "1", min_confidence=0.8)
    for intent, mode, route in (
        ("add_product", _WORKFLOW, "cart_management"),
        ("remove_product", _WORKFLOW, "cart_management"),
        ("cancel_order", _WORKFLOW, "cancel_order"),
        ("change_order", _WORKFLOW, "change_order"),
        ("request_invoice", _WORKFLOW, "invoice_request"),
        ("track_order", _READONLY, "order_query"),
        ("order_history", _READONLY, "order_query"),
        ("track_delivery", _READONLY, "delivery_query"),
        ("delivery_time", _READONLY, "delivery_query"),
        ("delivery_issue", _WORKFLOW, "delivery_issue"),
        ("missing_item", _WORKFLOW, "delivery_issue"),
        ("damaged_delivery", _WORKFLOW, "delivery_issue"),
        ("wrong_item", _WORKFLOW, "delivery_issue"),
        ("shipping_costs", _READONLY, "shipping_policy"),
        ("request_refund", _WORKFLOW, "refund"),
        ("refund_status", _READONLY, "refund_query"),
        ("refund_policy", _READONLY, "refund_policy"),
        ("return_policy", _READONLY, "return_policy"),
        ("return_product", _WORKFLOW, "return"),
        ("exchange_product", _WORKFLOW, "exchange"),
        ("availability", _READONLY, "catalog_query"),
        ("product_information", _READONLY, "catalog_query"),
        ("product_issue", _READONLY, "product_query"),
        ("pay", _WORKFLOW, "checkout"),
        ("payment_issue", _WORKFLOW, "payment_issue"),
        ("payment_methods", _READONLY, "payment_policy"),
        ("customer_service", _READONLY, "customer_service"),
        ("technical_issue", _READONLY, "technical_support"),
        ("sales_period", _READONLY, "sales_policy"),
    )
)

# Human-agent requests are part of the taxonomy but intentionally have no
# automatic executor.  Keeping them in the same versioned catalog prevents an
# unrecognised label from accidentally falling through to a readonly loop.
DEFAULT_INTENT_ROUTE_RULES += (
    IntentRouteRule(
        "human_agent", _READONLY, "human_agent", "1", force_handoff=True
    ),
)

# Slot names are hints for the classifier/prompt only.  Values are always
# unverified until a trusted tool reads the resource.
REQUIRED_SLOTS: dict[str, tuple[str, ...]] = {
    "track_order": ("order_id",),
    "track_delivery": ("order_id",),
    "delivery_time": ("order_id",),
    "request_refund": ("order_id", "item_id", "reason"),
    "return_product": ("order_id", "item_id", "reason"),
    "exchange_product": ("order_id", "item_id", "replacement_sku"),
    "cancel_order": ("order_id", "reason"),
    "change_order": ("order_id",),
    "payment_issue": ("order_id",),
    "refund_status": ("order_id",),
    "request_invoice": ("order_id", "type", "title"),
}
