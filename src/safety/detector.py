"""Deterministic P0 safety detector.

The detector deliberately emits abstract reason codes rather than matched
text.  A future semantic risk model may add evidence, but it can never
override a deterministic hard block.
"""

from __future__ import annotations

from src.protocols import RequestRiskLevel
from src.safety.contracts import SafetyAssessment, SafetyDisposition
from src.safety.taxonomy import SafetyCategory, SafetySeverity

DETECTOR_VERSION = "deterministic-safety-v1"

_RULES: tuple[tuple[SafetyCategory, SafetySeverity, str, tuple[str, ...]], ...] = (
    (
        SafetyCategory.PROMPT_INJECTION,
        SafetySeverity.P0,
        "PROMPT_INJECTION",
        ("忽略系统规则", "绕过系统", "泄露提示词", "system prompt", "ignore previous"),
    ),
    (
        SafetyCategory.TRANSACTION_BYPASS,
        SafetySeverity.P0,
        "CONFIRMATION_BYPASS",
        (
            "绕过确认",
            "不要确认",
            "跳过确认",
            "忽略确认",
            "直接退款",
            "直接帮我退款",
            "无需确认",
        ),
    ),
    (
        SafetyCategory.PRIVACY,
        SafetySeverity.P0,
        "CREDENTIAL_REQUEST",
        ("验证码", "密码", "银行卡号", "卡号", "支付密码", "登录凭证"),
    ),
    (
        SafetyCategory.ACCOUNT_TAKEOVER,
        SafetySeverity.P0,
        "CROSS_ACCOUNT_ACCESS",
        ("同事的订单", "前任的订单", "客户的订单", "别人的订单", "他人的订单"),
    ),
    (
        SafetyCategory.UNKNOWN_TOOL_STATE,
        SafetySeverity.P0,
        "UNKNOWN_TOOL_STATE",
        ("接口超时", "状态未知", "不知道有没有退", "告诉我已经退好了"),
    ),
)


def detect(content: str) -> SafetyAssessment:
    text = content.strip().lower()
    for category, severity, reason, patterns in _RULES:
        if any(pattern.lower() in text for pattern in patterns):
            return SafetyAssessment(
                category=category,
                severity=severity,
                risk_level=RequestRiskLevel.HIGH,
                reason_code=reason,
                hard_block=True,
                disposition=SafetyDisposition.HANDOFF,
                safe_next_step="停止自动操作并由人工核验",
                detector_version=DETECTOR_VERSION,
                matched=True,
            )
    return SafetyAssessment(
        category=SafetyCategory.NONE,
        severity=SafetySeverity.P2,
        risk_level=RequestRiskLevel.UNKNOWN,
        reason_code="RISK_REQUIRES_INTENT_TRIAGE",
        hard_block=False,
        disposition=SafetyDisposition.CONTINUE,
        safe_next_step="继续执行受控意图识别",
        detector_version=DETECTOR_VERSION,
        matched=False,
    )


__all__ = ["DETECTOR_VERSION", "detect"]
