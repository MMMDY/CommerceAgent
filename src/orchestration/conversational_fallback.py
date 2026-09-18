"""Bounded, code-owned replies for low-risk non-commerce conversations."""

from __future__ import annotations

from src.orchestration.capabilities import capability_summary


def response_for(*, intent: str, content: str) -> str:
    """Return a warm but domain-bounded response without opening general QA."""

    text = content.strip()
    if intent == "greeting":
        return "你好！我是 CommerceAgent，可以帮你查询订单、物流、商品信息和售后政策。"
    if intent == "thanks":
        return "不客气！如果还需要查询订单或商品信息，随时告诉我。"
    if intent == "capability_query":
        return (
            f"我可以协助{capability_summary()}；"
            "涉及账户或交易变更时，我会先校验并请求确认。"
        )
    if intent == "social_chat":
        if any(marker in text for marker in ("心情很好", "开心", "高兴", "快乐")):
            return (
                "太棒了！你的好心情很有感染力，今天的你值得一个大大的夸奖："
                "阳光、可爱又充满能量！"
            )
        return (
            "听起来你想轻松聊聊，我很愿意接住这份好心情。"
            "需要我帮你查询订单或商品信息时，也可以直接告诉我。"
        )
    return (
        "我目前主要提供订单、物流、商品和售后政策服务；"
        "这个问题暂不在服务范围内，但你可以换一种相关问法试试。"
    )


__all__ = ["response_for"]
