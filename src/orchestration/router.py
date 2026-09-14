"""Fail-closed conversion from model classification candidates to a route."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.protocols import ExecutionMode, IntentClassification, RiskHint, ToolRisk


class RouteOutcome(StrEnum):
    EXECUTE = "execute"
    HANDOFF = "handoff"


class RouteDecision(BaseModel):
    """Trusted route result; unlike IntentClassification this may select an executor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: RouteOutcome
    execution_mode: ExecutionMode | None = None
    workflow_id: str | None = Field(default=None, min_length=1, max_length=128)
    workflow_version: str | None = Field(default=None, min_length=1, max_length=64)
    intent: str | None = Field(default=None, min_length=1, max_length=128)
    reason_code: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_complete_execute_target(self) -> RouteDecision:
        execute = self.outcome is RouteOutcome.EXECUTE
        has_target = all(
            value is not None
            for value in (self.execution_mode, self.workflow_id, self.workflow_version, self.intent)
        )
        if execute != has_target:
            raise ValueError("execute route must contain exactly one complete target")
        return self


@dataclass(frozen=True, slots=True)
class IntentRouteRule:
    intent: str
    execution_mode: ExecutionMode
    workflow_id: str
    workflow_version: str
    min_confidence: float = 0.8


class IntentRouter:
    """Code-owned route map and risk escalation boundary."""

    def __init__(self, rules: tuple[IntentRouteRule, ...]) -> None:
        self._rules = {rule.intent: rule for rule in rules}
        if len(self._rules) != len(rules):
            raise ValueError("duplicate intent route rule")

    def decide(
        self,
        candidate: IntentClassification,
        *,
        target_tool_risk: ToolRisk | None = None,
    ) -> RouteDecision:
        rule = self._rules.get(candidate.intent)
        if rule is None:
            return self._handoff("UNKNOWN_INTENT")
        if candidate.confidence < rule.min_confidence:
            return self._handoff("LOW_CLASSIFICATION_CONFIDENCE")

        required_mode = rule.execution_mode
        if candidate.risk_hint is RiskHint.WRITE:
            if required_mode is ExecutionMode.READONLY_LOOP:
                return self._handoff("CLASSIFICATION_RISK_CONFLICT")
            required_mode = ExecutionMode.WORKFLOW
        if target_tool_risk is not None and target_tool_risk is not ToolRisk.READ_ONLY:
            if required_mode is ExecutionMode.READONLY_LOOP:
                return self._handoff("TOOL_RISK_CONFLICT")
            required_mode = ExecutionMode.WORKFLOW

        return RouteDecision(
            outcome=RouteOutcome.EXECUTE,
            execution_mode=required_mode,
            workflow_id=rule.workflow_id,
            workflow_version=rule.workflow_version,
            intent=rule.intent,
            reason_code="ROUTE_RULE_MATCHED",
        )

    @staticmethod
    def _handoff(reason_code: str) -> RouteDecision:
        return RouteDecision(outcome=RouteOutcome.HANDOFF, reason_code=reason_code)
