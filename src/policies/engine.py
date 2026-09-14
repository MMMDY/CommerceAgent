"""A deliberately small, auditable policy rule interpreter.

The interpreter accepts facts collected by trusted runtime/tool code only.  It
does not evaluate Python expressions, templates, SQL, or model-provided rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Any


class PolicyEngineError(ValueError):
    """A policy definition uses a capability outside the supported DSL."""


class PolicyEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_HANDOFF = "require_handoff"


_OPERATORS = frozenset({"eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in"})
_EFFECT_ORDER = {
    PolicyEffect.ALLOW: 0,
    PolicyEffect.REQUIRE_HANDOFF: 1,
    PolicyEffect.DENY: 2,
}


@dataclass(frozen=True, slots=True)
class FactCondition:
    fact: str
    op: str
    value: object


@dataclass(frozen=True, slots=True)
class PolicyRule:
    rule_id: str
    applies_to: str
    priority: int
    conditions: tuple[FactCondition, ...]
    effect: PolicyEffect
    reason_code: str


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    policy_version: str
    effect: PolicyEffect
    rule_ids: tuple[str, ...]
    reason_code: str
    facts_hash: str


class PolicyEngine:
    """Immutable policy catalog with a fixed fact and operator allowlist."""

    def __init__(
        self,
        *,
        version: str,
        allowed_facts: frozenset[str],
        rules: tuple[PolicyRule, ...],
    ) -> None:
        if not version:
            raise PolicyEngineError("policy version must not be empty")
        if len({rule.rule_id for rule in rules}) != len(rules):
            raise PolicyEngineError("duplicate policy rule id")
        for rule in rules:
            for condition in rule.conditions:
                if condition.fact not in allowed_facts:
                    raise PolicyEngineError("policy rule uses an unapproved fact")
                if condition.op not in _OPERATORS:
                    raise PolicyEngineError("policy rule uses an unapproved operator")
                if isinstance(condition.value, dict | set):
                    raise PolicyEngineError("policy constants must be scalar or a list")
        self.version = version
        self._allowed_facts = allowed_facts
        self._rules = tuple(rules)

    def evaluate(self, *, action: str, facts: dict[str, Any]) -> PolicyDecision:
        unknown = set(facts).difference(self._allowed_facts)
        if unknown:
            raise PolicyEngineError("unapproved policy fact supplied")
        facts_hash = self._facts_hash(facts)
        candidates = tuple(rule for rule in self._rules if rule.applies_to == action)
        required = {condition.fact for rule in candidates for condition in rule.conditions}
        if required.difference(facts):
            return self._decision(PolicyEffect.DENY, (), "MISSING_REQUIRED_FACTS", facts_hash)
        matched = tuple(rule for rule in candidates if self._matches(rule, facts))
        if not matched:
            return self._decision(PolicyEffect.DENY, (), "NO_POLICY_RULE_MATCHED", facts_hash)
        winning_effect = max((rule.effect for rule in matched), key=_EFFECT_ORDER.__getitem__)
        winning = tuple(
            sorted(
                (rule for rule in matched if rule.effect is winning_effect),
                key=lambda rule: (-rule.priority, rule.rule_id),
            )
        )
        return self._decision(
            winning_effect,
            tuple(rule.rule_id for rule in winning),
            winning[0].reason_code,
            facts_hash,
        )

    def _decision(
        self, effect: PolicyEffect, rule_ids: tuple[str, ...], reason_code: str, facts_hash: str
    ) -> PolicyDecision:
        return PolicyDecision(self.version, effect, rule_ids, reason_code, facts_hash)

    @staticmethod
    def _facts_hash(facts: dict[str, Any]) -> str:
        encoded = dumps(
            facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        return f"sha256:{sha256(encoded.encode()).hexdigest()}"

    @staticmethod
    def _matches(rule: PolicyRule, facts: dict[str, Any]) -> bool:
        return all(
            PolicyEngine._matches_condition(condition, facts[condition.fact])
            for condition in rule.conditions
        )

    @staticmethod
    def _matches_condition(condition: FactCondition, actual: object) -> bool:
        expected = condition.value
        if condition.op == "eq":
            return actual == expected
        if condition.op == "ne":
            return actual != expected
        if condition.op == "lt":
            return bool(actual < expected)  # type: ignore[operator]
        if condition.op == "lte":
            return bool(actual <= expected)  # type: ignore[operator]
        if condition.op == "gt":
            return bool(actual > expected)  # type: ignore[operator]
        if condition.op == "gte":
            return bool(actual >= expected)  # type: ignore[operator]
        if condition.op == "in":
            return bool(actual in expected)  # type: ignore[operator]
        return bool(actual not in expected)  # type: ignore[operator]
