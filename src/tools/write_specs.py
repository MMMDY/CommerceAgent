"""Model-visible prepare capabilities for Phase 4 mutation workflows.

These specs stop at preview/slot collection.  No commit adapter is registered
in the model-facing registry; commit is owned by the confirmation endpoint
and durable mutation boundary.
"""

# ruff: noqa: E501

from __future__ import annotations

from src.protocols import ResourceBinding, RetryPolicy, ToolRisk, ToolSpec

_RETRY = RetryPolicy(max_attempts=1, backoff_ms=())
_STRING = {"type": "string"}
_WORKFLOW_STEPS = ("authenticate", "load_resource", "check_eligibility", "collect_slots", "prepare")


def _prepare_spec(name: str, properties: dict[str, object], required: list[str], workflow: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="1",
        input_schema={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        output_schema={
            "type": "object",
            "properties": {"preview": {"type": "object"}, "missing_slots": {"type": "array"}},
            "required": ["preview", "missing_slots"],
            "additionalProperties": False,
        },
        risk=ToolRisk.PREPARE,
        required_scopes=("order:write",),
        timeout_ms=3_000,
        retry_policy=_RETRY,
        model_visible=True,
        allowed_workflows=(f"{workflow}@1",),
        allowed_steps=_WORKFLOW_STEPS,
        resource_binding=ResourceBinding(argument="order_id", owner_check="order.owner"),
    )


def prepare_tool_specs() -> tuple[ToolSpec, ...]:
    return (
        _prepare_spec("prepare_cancel_order", {"order_id": _STRING, "reason": _STRING}, ["order_id", "reason"], "cancel_order"),
        _prepare_spec("prepare_update_shipping_address", {"order_id": _STRING, "new_address": _STRING}, ["order_id", "new_address"], "change_order"),
        _prepare_spec("prepare_refund", {"order_id": _STRING, "item_id": _STRING, "reason": _STRING}, ["order_id", "item_id", "reason"], "refund"),
        _prepare_spec("prepare_return", {"order_id": _STRING, "item_id": _STRING, "reason": _STRING}, ["order_id", "item_id", "reason"], "return"),
        _prepare_spec("prepare_exchange", {"order_id": _STRING, "item_id": _STRING, "replacement_sku": _STRING}, ["order_id", "item_id", "replacement_sku"], "exchange"),
    )
