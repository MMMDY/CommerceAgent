"""Code-owned capability directory used by user-facing capability replies."""

from __future__ import annotations

SUPPORTED_CAPABILITIES: tuple[str, ...] = (
    "查询订单与物流",
    "说明商品信息",
    "说明退款/退货政策",
)


def capability_summary() -> str:
    return "、".join(SUPPORTED_CAPABILITIES)


__all__ = ["SUPPORTED_CAPABILITIES", "capability_summary"]
