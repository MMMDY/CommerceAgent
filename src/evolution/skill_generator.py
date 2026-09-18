"""Build a review-only Skill candidate from a failure cluster."""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from src.evolution.skill_validator import validate_skill_definition


def build_skill_candidate(
    *,
    cluster_key: str,
    source_count: int,
    keywords: list[str],
    response_policy: str,
    scope_type: str = "tenant",
    scope_value: str = "tenant",
    ttl_days: int = 30,
) -> dict[str, Any]:
    # Examples are abstract boundary labels, not copied failure text. The
    # generator intentionally has no access to raw user conversations.
    forbidden_tools = ["business_write_tools", "unknown_risk_tools"]
    definition = {
        "trigger": {"keywords": keywords[:32]},
        "response_policy": response_policy,
        "allowed_actions": ["respond"],
        "allowed_decisions": ["respond", "finish"],
        "forbidden_tools": forbidden_tools,
        "scope": {"type": scope_type, "value": scope_value},
        "positive_examples": ["同类低风险模糊请求"],
        "negative_examples": ["涉及交易、账户或高风险动作的请求"],
        "ttl_seconds": ttl_days * 86400,
        "cluster_key": cluster_key,
    }
    valid, errors = validate_skill_definition(definition)
    if not valid:
        raise ValueError("invalid_skill_definition:" + ",".join(errors))
    return {
        "trigger": definition["trigger"],
        "strategy": {
            "response_policy": response_policy,
            "allowed_decisions": definition["allowed_decisions"],
            "forbidden_tools": forbidden_tools,
            "ttl_seconds": definition["ttl_seconds"],
        },
        "provenance": {"cluster_key": cluster_key, "source_count": source_count},
        "definition": definition,
    }


__all__ = ["build_skill_candidate"]
