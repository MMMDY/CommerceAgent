"""Reject unsafe model decisions before any tool side effect."""

from __future__ import annotations

from dataclasses import dataclass

from src.protocols import Decision, DecisionType, ToolSpec

SYSTEM_ARGUMENT_FIELDS = frozenset(
    {
        "tenant_id",
        "actor_id",
        "owner_id",
        "scopes",
        "idempotency_key",
        "confirmation_token",
        "policy_version",
    }
)


class DecisionValidationError(ValueError):
    """The model proposed an action outside the current trusted boundary."""

    @property
    def error_code(self) -> str:
        message = str(self)
        if "evidence" in message:
            return "UNTRUSTED_EVIDENCE"
        if "route" in message:
            return "ROUTE_MISMATCH"
        if "tool" in message:
            return "TOOL_NOT_ALLOWED"
        if "argument" in message:
            return "INVALID_TOOL_ARGUMENT"
        return "DECISION_REJECTED"


@dataclass(frozen=True, slots=True)
class DecisionBoundary:
    route: str
    allowed_types: frozenset[DecisionType]
    allowed_tools: frozenset[str]
    trusted_evidence_ids: frozenset[str]
    allowed_routes: frozenset[str] = frozenset()


class DecisionValidator:
    def validate(
        self, *, decision: Decision, boundary: DecisionBoundary, tool_spec: ToolSpec | None = None
    ) -> None:
        if decision.type not in boundary.allowed_types:
            raise DecisionValidationError("decision type is not allowed")
        if decision.route != boundary.route and decision.route not in boundary.allowed_routes:
            raise DecisionValidationError("decision route does not match runtime route")
        if not set(decision.evidence_ids).issubset(boundary.trusted_evidence_ids):
            raise DecisionValidationError("decision references untrusted evidence")
        if set(decision.args).intersection(SYSTEM_ARGUMENT_FIELDS):
            raise DecisionValidationError("decision attempted to set a system argument")
        if decision.type is DecisionType.CALL_TOOL:
            if decision.tool is None or decision.tool not in boundary.allowed_tools:
                raise DecisionValidationError("decision tool is not allowed")
            if tool_spec is None or tool_spec.name != decision.tool:
                raise DecisionValidationError("decision tool specification is unavailable")
            self._validate_arguments(decision.args, tool_spec.input_schema)
        elif decision.tool is not None or decision.args:
            raise DecisionValidationError("non-tool decision includes tool data")

    @staticmethod
    def _validate_arguments(arguments: dict[str, object], schema: dict[str, object]) -> None:
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(required, list) or not isinstance(properties, dict):
            raise DecisionValidationError("tool schema is invalid")
        if any(name not in arguments for name in required):
            raise DecisionValidationError("tool argument is missing")
        if schema.get("additionalProperties") is False and set(arguments) - set(properties):
            raise DecisionValidationError("tool argument is unknown")
        for name, value in arguments.items():
            definition = properties.get(name)
            if not isinstance(definition, dict):
                continue
            expected_type = definition.get("type")
            if expected_type == "string" and not isinstance(value, str):
                raise DecisionValidationError("tool argument type is invalid")
            if expected_type == "integer" and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise DecisionValidationError("tool argument type is invalid")
