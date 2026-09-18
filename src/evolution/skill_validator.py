"""Hard validation for generated Skills before they can enter human review."""

from __future__ import annotations

import re
from typing import Any

_ALLOWED_POLICIES = {
    "conversational_response",
    "graceful_unsupported",
    "safety_deescalation",
}
_ALLOWED_ACTIONS = {"respond", "finish"}
_FORBIDDEN_KEYS = {
    "tool",
    "tools",
    "allowed_tools",
    "route",
    "permissions",
    "code",
    "sql",
    "url",
    "external_url",
    "system_prompt",
}
_DANGEROUS_TEXT = re.compile(
    r"(?i)(?:https?://|www\.|```|\b(?:select|insert|update|delete|drop|alter)\s+|\b(?:exec|eval|os\.system|subprocess)\s*\()"
)
_MAX_EXAMPLES = 16
_MAX_EXAMPLE_LENGTH = 240


def validate_skill_definition(definition: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    trigger = definition.get("trigger")
    if not isinstance(trigger, dict):
        errors.append("trigger_required")
    else:
        keywords = trigger.get("keywords")
        if not isinstance(keywords, list) or not 1 <= len(keywords) <= 32:
            errors.append("trigger_keywords_required")
        elif any(
            not isinstance(item, str) or not 1 <= len(item.strip()) <= 128
            for item in keywords
        ):
            errors.append("invalid_trigger_keyword")
    policy = definition.get("response_policy")
    if not isinstance(policy, str):
        errors.append("response_policy_required")
    elif policy not in _ALLOWED_POLICIES:
        errors.append("unsafe_response_policy")
    actions = definition.get("allowed_actions", ["respond", "finish"])
    if not isinstance(actions, list) or any(
        not isinstance(item, str) or item not in _ALLOWED_ACTIONS for item in actions
    ):
        errors.append("unsafe_action")
    decisions = definition.get("allowed_decisions", ["respond", "finish"])
    if not isinstance(decisions, list) or any(
        not isinstance(item, str) or item not in _ALLOWED_ACTIONS for item in decisions
    ):
        errors.append("unsafe_decision_set")
    scope = definition.get("scope")
    if (
        not isinstance(scope, dict)
        or scope.get("type") not in {"tenant", "route", "global"}
        or not isinstance(scope.get("value"), str)
        or not scope["value"].strip()
    ):
        errors.append("scope_required")
    forbidden_tools = definition.get("forbidden_tools")
    if not isinstance(forbidden_tools, list) or any(
        not isinstance(item, str) or not 1 <= len(item.strip()) <= 128
        for item in forbidden_tools
    ):
        errors.append("forbidden_tools_required")
    ttl_seconds = definition.get("ttl_seconds")
    if (
        not isinstance(ttl_seconds, int)
        or isinstance(ttl_seconds, bool)
        or not 1 <= ttl_seconds <= 90 * 86400
    ):
        errors.append("invalid_ttl")
    for field in ("positive_examples", "negative_examples"):
        examples = definition.get(field)
        if not isinstance(examples, list) or not 1 <= len(examples) <= _MAX_EXAMPLES or any(
            not isinstance(item, str) or not 1 <= len(item.strip()) <= _MAX_EXAMPLE_LENGTH
            for item in examples
        ):
            errors.append(f"invalid_{field}")
    for key, value in definition.items():
        if key.casefold() in _FORBIDDEN_KEYS:
            errors.append("capability_expansion")
        if _contains_dangerous_text(value):
            errors.append("unsafe_instruction_text")
    return not errors, tuple(errors)


def _contains_dangerous_text(value: Any) -> bool:
    if isinstance(value, str):
        return _DANGEROUS_TEXT.search(value) is not None
    if isinstance(value, dict):
        return any(_contains_dangerous_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_dangerous_text(item) for item in value)
    return False


__all__ = ["validate_skill_definition"]
