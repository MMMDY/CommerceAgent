"""Code-owned mutation planning and demo business boundary.

The model may identify a mutation and provide user-entered slots, but this
module owns normalization, resource ownership, eligibility and the preview
that is later bound to a confirmation token.  No commit method is exposed to
the model-facing tool registry.
"""

# ruff: noqa: E501

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from typing import Any


class MutationPlanningError(ValueError):
    """A mutation cannot safely reach the confirmation boundary."""

    def __init__(self, code: str, message: str, *, missing_slots: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.missing_slots = missing_slots


MUTATION_WORKFLOW_VERSIONS: dict[str, str] = {
    "cancel_order": "cancel-order-v1",
    "change_order": "update-shipping-address-v1",
    "request_refund": "refund-v1",
    "return_product": "return-v1",
    "exchange_product": "exchange-v1",
}

MUTATION_REQUIRED_SLOTS: dict[str, tuple[str, ...]] = {
    "cancel_order": ("order_id", "reason"),
    "change_order": ("order_id", "new_address"),
    "request_refund": ("order_id", "item_id", "reason"),
    "return_product": ("order_id", "item_id", "reason"),
    "exchange_product": ("order_id", "item_id", "replacement_sku"),
}

_ORDER_PATTERN = re.compile(r"\bORD-[A-Z0-9-]{3,40}\b", re.IGNORECASE)
_SKU_PATTERN = re.compile(r"\b[A-Z]{2,8}[0-9][A-Z0-9/-]{2,24}\b", re.IGNORECASE)
_REASON_NORMALIZATION = {
    "不想要": "changed_mind",
    "不需要": "changed_mind",
    "质量": "quality_issue",
    "坏": "quality_issue",
    "损坏": "quality_issue",
    "错发": "wrong_item",
    "不合适": "not_suitable",
    "其他": "other",
}


@dataclass(frozen=True, slots=True)
class DemoOrder:
    order_id: str
    owner_id: str
    status: str
    item_id: str
    item_title: str
    amount: int
    quantity: int = 1
    currency: str = "CNY"


@dataclass(frozen=True, slots=True)
class MutationPreview:
    mutation_type: str
    workflow_version: str
    resource_ref: str
    operation: str
    summary: str
    impact: dict[str, Any]
    amount: dict[str, Any]
    channel: str
    estimated_time: str
    policy_version: str
    normalized_args: dict[str, Any]

    def as_public(self) -> dict[str, Any]:
        """Return the confirmation-card payload; never include token data."""

        return {
            "mutation_type": self.mutation_type,
            "workflow_version": self.workflow_version,
            "resource_ref": self.resource_ref,
            "operation": self.operation,
            "summary": self.summary,
            "impact": self.impact,
            "amount": self.amount,
            "channel": self.channel,
            "estimated_time": self.estimated_time,
            "policy_version": self.policy_version,
        }


DEFAULT_DEMO_ORDERS: tuple[DemoOrder, ...] = (
    DemoOrder("ORD-DEMO-001", "demo-user-001", "shipped", "TAH6206", "无线蓝牙耳机", 299),
    DemoOrder("ORD-DEMO-002", "demo-user-001", "delivered", "BHD308/10", "ThermoProtect 吹风机", 199),
    DemoOrder("ORD-DEMO-CANCEL-001", "demo-user-001", "processing", "TAH6206", "无线蓝牙耳机", 299),
    DemoOrder("ORD-DEMO-003", "demo-user-002", "processing", "HD928X", "智能空气炸锅", 899),
)


class MutationPlanner:
    """Pure planner backed by immutable demo resources."""

    def __init__(self, orders: tuple[DemoOrder, ...] = DEFAULT_DEMO_ORDERS) -> None:
        self._orders = {item.order_id: item for item in orders}

    def prepare(
        self,
        *,
        mutation_type: str,
        actor_id: str,
        arguments: dict[str, object],
        policy_version: str = "phase4-policy-v1",
    ) -> MutationPreview:
        if mutation_type not in MUTATION_WORKFLOW_VERSIONS:
            raise MutationPlanningError("UNKNOWN_MUTATION", "暂不支持该变更")
        normalized = normalize_arguments(mutation_type, arguments)
        missing = tuple(
            slot
            for slot in MUTATION_REQUIRED_SLOTS[mutation_type]
            if not normalized.get("reason_code" if slot == "reason" else slot)
        )
        if missing:
            raise MutationPlanningError("MISSING_SLOTS", "还需要补充必要信息", missing_slots=missing)
        order_id = str(normalized["order_id"])
        order = self._orders.get(order_id)
        if order is None or order.owner_id != actor_id:
            # Do not reveal whether another actor's resource exists.
            raise MutationPlanningError("RESOURCE_NOT_FOUND", "未找到可操作的订单")
        quantity_value = normalized.get("quantity", 1)
        if not isinstance(quantity_value, int) or isinstance(quantity_value, bool) or quantity_value != 1:
            raise MutationPlanningError("INVALID_QUANTITY", "当前演示订单仅支持操作可操作数量为 1 的商品")
        normalized["quantity"] = 1
        self._check_eligibility(mutation_type, order)
        reason_code = str(normalized.get("reason_code", "other"))
        item_id = str(normalized.get("item_id", order.item_id))
        if item_id != order.item_id:
            raise MutationPlanningError("ITEM_NOT_FOUND", "订单中没有该商品")
        if mutation_type == "change_order":
            address = str(normalized["new_address"])
            impact = {"address": _mask_address(address), "address_version": "v1", "quantity": 1}
            amount = {"value": 0, "currency": order.currency}
            channel, eta = "原配送渠道", "预计 1 个工作日内生效"
            summary = f"修改订单 {order.order_id} 的收货地址"
        elif mutation_type == "cancel_order":
            impact = {"order_status": "cancelled", "item_id": order.item_id, "quantity": 1}
            amount = {"value": order.amount, "currency": order.currency}
            channel, eta = "原支付渠道", "预计 1-3 个工作日到账"
            summary = f"取消订单 {order.order_id}"
        elif mutation_type == "request_refund":
            impact = {"refund_status": "requested", "item_id": item_id, "reason_code": reason_code, "quantity": 1}
            amount = {"value": order.amount, "currency": order.currency}
            channel, eta = "原支付渠道", "预计 3-7 个工作日到账"
            summary = f"申请订单 {order.order_id} 的退款"
        elif mutation_type == "return_product":
            impact = {"return_status": "requested", "item_id": item_id, "reason_code": reason_code, "quantity": 1}
            amount = {"value": order.amount, "currency": order.currency}
            channel, eta = "原支付渠道", "收到退回商品后 3-7 个工作日"
            summary = f"申请退回订单 {order.order_id} 的商品"
        else:
            replacement = str(normalized["replacement_sku"])
            impact = {"exchange_status": "requested", "item_id": item_id, "replacement_sku": replacement, "quantity": 1}
            amount = {"value": 0, "currency": order.currency}
            channel, eta = "原配送渠道", "预计 3-5 个工作日"
            summary = f"申请将订单 {order.order_id} 的商品换为 {replacement}"
        return MutationPreview(
            mutation_type=mutation_type,
            workflow_version=MUTATION_WORKFLOW_VERSIONS[mutation_type],
            resource_ref=order.order_id,
            operation={
                "cancel_order": "commit_cancel_order",
                "change_order": "commit_update_shipping_address",
                "request_refund": "commit_refund",
                "return_product": "commit_return",
                "exchange_product": "commit_exchange",
            }[mutation_type],
            summary=summary,
            impact=impact,
            amount=amount,
            channel=channel,
            estimated_time=eta,
            policy_version=policy_version,
            normalized_args=normalized,
        )

    @staticmethod
    def _check_eligibility(mutation_type: str, order: DemoOrder) -> None:
        if mutation_type == "cancel_order" and order.status not in {"processing", "paid"}:
            raise MutationPlanningError("POLICY_DENIED", "该订单当前状态不支持取消")
        if mutation_type == "change_order" and order.status not in {"processing", "paid"}:
            raise MutationPlanningError("POLICY_DENIED", "该订单当前状态不支持修改地址")


def normalize_arguments(mutation_type: str, arguments: dict[str, object]) -> dict[str, Any]:
    """Normalize user/model slots; never let a model choose reason enums."""

    normalized: dict[str, Any] = {}
    if arguments.get("order_id"):
        normalized["order_id"] = str(arguments["order_id"]).upper()
    if arguments.get("item_id"):
        normalized["item_id"] = str(arguments["item_id"]).upper()
    if arguments.get("replacement_sku"):
        normalized["replacement_sku"] = str(arguments["replacement_sku"]).upper()
    if arguments.get("new_address"):
        normalized["new_address"] = _normalize_address(str(arguments["new_address"]))
    if arguments.get("reason"):
        raw = str(arguments["reason"]).strip()
        normalized["reason_code"] = next(
            (code for label, code in _REASON_NORMALIZATION.items() if label in raw), "other"
        )
    return normalized


def extract_arguments(mutation_type: str, text: str) -> dict[str, object]:
    """Small deterministic extractor used before prepare; values stay untrusted."""

    arguments: dict[str, object] = {}
    order = _ORDER_PATTERN.search(text)
    if order:
        arguments["order_id"] = order.group(0)
    skus = _SKU_PATTERN.findall(text)
    if mutation_type == "exchange_product" and skus:
        arguments["replacement_sku"] = skus[-1]
    if mutation_type in {"request_refund", "return_product", "exchange_product"} and order:
        arguments["item_id"] = skus[0] if skus else ""
    if mutation_type in {"cancel_order", "request_refund", "return_product"}:
        arguments["reason"] = text
    if mutation_type == "change_order":
        marker = max(text.find("地址"), text.find("改为"))
        if marker >= 0:
            candidate = text[marker + 2 :].strip(" ：:，,。")
            if candidate:
                arguments["new_address"] = candidate
    return arguments


def preview_hash(preview: MutationPreview) -> str:
    encoded = dumps(preview.as_public(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(encoded.encode()).hexdigest()}"


def arguments_hash(arguments: dict[str, Any]) -> str:
    encoded = dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(encoded.encode()).hexdigest()}"


def hash_secret(value: str) -> str:
    return f"sha256:{sha256(value.encode()).hexdigest()}"


def _normalize_address(value: str) -> str:
    value = " ".join(value.split())
    if not 6 <= len(value) <= 200:
        raise MutationPlanningError("INVALID_ARGUMENT", "收货地址长度不合法")
    return value


def _mask_address(value: str) -> str:
    if len(value) <= 6:
        return "***"
    return value[:4] + "***" + value[-3:]
