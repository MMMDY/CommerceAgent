"""Stable safety taxonomy used by detection, evaluation and release gates."""

from __future__ import annotations

from enum import StrEnum


class SafetyCategory(StrEnum):
    ACCOUNT_TAKEOVER = "account_takeover"
    TRANSACTION_BYPASS = "transaction_bypass"
    PRIVACY = "privacy"
    PROMPT_INJECTION = "prompt_injection"
    UNKNOWN_TOOL_STATE = "unknown_tool_state"
    HUMAN_SAFETY = "human_safety"
    NONE = "none"


class SafetySeverity(StrEnum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"


__all__ = ["SafetyCategory", "SafetySeverity"]
