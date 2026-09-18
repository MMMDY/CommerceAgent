"""Safe, user-facing responses for safety boundaries."""

from __future__ import annotations

# ruff: noqa: E501
from src.safety.taxonomy import SafetyCategory

_RESPONSES = {
    SafetyCategory.PROMPT_INJECTION: "我不能提供系统提示或内部凭据。请告诉我你要办理的订单或售后事项，我可以在安全范围内协助。",
    SafetyCategory.TRANSACTION_BYPASS: "涉及退款或其他交易变更时不能跳过确认。我会停止自动操作，并请人工核验后再继续。",
    SafetyCategory.PRIVACY: "我不能索取或提供密码、验证码、银行卡号等敏感信息。请通过官方安全渠道完成身份验证。",
    SafetyCategory.ACCOUNT_TAKEOVER: "我只能协助核验你本人有权访问的订单，不能处理他人账户或订单信息。请提供本人订单的公开编号。",
    SafetyCategory.UNKNOWN_TOOL_STATE: "当前业务状态无法确认，我不会把未知状态说成已成功。请暂缓重复操作，并由人工核验最终状态。",
    SafetyCategory.HUMAN_SAFETY: "这个问题需要经过人工安全审核。我会先暂停自动处理，并提供人工协助入口。",
}


def safe_response_for(category: SafetyCategory) -> str:
    return _RESPONSES.get(
        category,
        "我暂时无法安全确认这个请求，会先暂停自动操作并请人工核验。",
    )


__all__ = ["safe_response_for"]
