"""Minimal, redacted persistence for model invocations."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from json import dumps
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.cost.calculator import CostCalculator
from src.cost.models import ModelPricing
from src.models.gateway import ModelDecision
from src.protocols import (
    IntentClassification,
    PromptView,
    RoutingPromptView,
    RunContext,
    TokenUsage,
)
from src.repositories.pricing import PricingRepository


class ModelInvocationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._pricing = PricingRepository(engine)

    def record_success(
        self,
        *,
        context: RunContext,
        prompt: PromptView,
        result: ModelDecision,
        provider: str,
        model: str,
        config_hash: str,
    ) -> None:
        input_metadata = {
            "workflow_id": prompt.workflow_id,
            "workflow_version": prompt.workflow_version,
            "step": prompt.current_step,
        }
        prompt_hash = _hash(prompt.model_dump_json())
        output_metadata = {
            "type": result.decision.type.value,
            "intent": result.decision.intent,
            "route": result.decision.route,
            "tool": result.decision.tool,
            "repaired": result.repaired,
        }
        usage = result.normalized_token_usage
        pricing = self._pricing.find(provider=provider, model=model) if usage is not None else None
        self._insert(
            context=context,
            step=prompt.current_step,
            provider=provider,
            model=model,
            config_hash=config_hash,
            prompt_version=prompt.system_policy_version,
            input_metadata=input_metadata,
            prompt_hash=prompt_hash,
            output_metadata=output_metadata,
            latency_ms=result.latency_ms,
            token_usage=usage,
            pricing=pricing,
            status="succeeded",
            error_code=None,
        )

    def record_failure(
        self,
        *,
        context: RunContext,
        prompt: PromptView,
        provider: str,
        model: str,
        config_hash: str,
        error_code: str,
    ) -> None:
        self._insert(
            context=context,
            step=prompt.current_step,
            provider=provider,
            model=model,
            config_hash=config_hash,
            prompt_version=prompt.system_policy_version,
            input_metadata={
                "workflow_id": prompt.workflow_id,
                "workflow_version": prompt.workflow_version,
                "step": prompt.current_step,
            },
            output_metadata=None,
            prompt_hash=_hash(prompt.model_dump_json()),
            latency_ms=None,
            token_usage=None,
            status="failed",
            error_code=error_code,
        )

    def record_classification_success(
        self,
        *,
        context: RunContext,
        prompt: RoutingPromptView,
        result: IntentClassification,
        provider: str,
        model: str,
        config_hash: str,
        latency_ms: int,
        token_usage: TokenUsage | None = None,
    ) -> None:
        pricing = (
            self._pricing.find(provider=provider, model=model)
            if token_usage is not None
            else None
        )
        self._insert(
            context=context,
            step="route_intent_risk",
            purpose="intent_classification",
            provider=provider,
            model=model,
            config_hash=config_hash,
            prompt_version="intent-classifier-v1",
            input_metadata={
                "allowed_intent_count": len(prompt.allowed_intents),
                "known_slot_count": len(prompt.known_slots),
            },
            prompt_hash=_hash(prompt.model_dump_json()),
            output_metadata={
                "intent": result.intent,
                "risk_hint": result.risk_hint.value,
                "route_hint": result.route_hint,
                "confidence": result.confidence,
                "domain_confidence": result.domain_confidence,
                "risk_confidence": result.risk_confidence,
                "required_slot_count": len(result.required_slots),
                "domain": result.domain.value,
                "request_risk_level": result.request_risk_level.value,
                "alternative_count": len(result.alternatives),
            },
            latency_ms=latency_ms,
            token_usage=token_usage,
            pricing=pricing,
            status="succeeded",
            error_code=None,
        )

    def _insert(
        self,
        *,
        context: RunContext,
        step: str,
        purpose: str = "agent",
        provider: str,
        model: str,
        config_hash: str,
        prompt_version: str,
        input_metadata: Mapping[str, object],
        output_metadata: Mapping[str, object] | None,
        prompt_hash: str,
        latency_ms: int | None,
        token_usage: TokenUsage | None = None,
        pricing: ModelPricing | None = None,
        status: str,
        error_code: str | None,
    ) -> None:
        input_json = dumps(
            input_metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        output_json = (
            dumps(output_metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if output_metadata is not None
            else None
        )
        cost = CostCalculator().calculate(usage=token_usage, pricing=pricing)
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO runtime.model_invocations "
                    "(model_call_id, run_id, step_id, purpose, provider, model, "
                    "model_config_hash, prompt_version, input_redacted_json, input_hash, "
                    "output_redacted_json, output_hash, status, error_code, latency_ms, "
                    "input_tokens, output_tokens, cached_input_tokens, reasoning_tokens, "
                    "total_tokens, usage_estimated, provider_usage_version, pricing_version_id, "
                    "cost_microusd, started_at, finished_at) "
                    "VALUES (:id, :run_id, :step, :purpose, :provider, :model, :config_hash, "
                    ":prompt_version, CAST(:input AS jsonb), :input_hash, CAST(:output AS jsonb), "
                    ":output_hash, :status, :error_code, :latency, :input_tokens, :output_tokens, "
                    ":cached_input_tokens, :reasoning_tokens, :total_tokens, :usage_estimated, "
                    ":provider_usage_version, :pricing_version_id, :cost_microusd, now(), now())"
                ),
                {
                    "id": uuid4(),
                    "run_id": context.run_id,
                    "step": step,
                    "purpose": purpose,
                    "provider": provider,
                    "model": model,
                    "config_hash": config_hash,
                    "prompt_version": prompt_version,
                    "input": input_json,
                    "input_hash": prompt_hash,
                    "output": output_json,
                    "output_hash": _hash(output_json) if output_json is not None else None,
                    "status": status,
                    "error_code": error_code,
                    "latency": latency_ms,
                    "input_tokens": getattr(token_usage, "input_tokens", None),
                    "output_tokens": getattr(token_usage, "output_tokens", None),
                    "cached_input_tokens": getattr(token_usage, "cached_input_tokens", None),
                    "reasoning_tokens": getattr(token_usage, "reasoning_tokens", None),
                    "total_tokens": getattr(token_usage, "total_tokens", None),
                    "usage_estimated": getattr(token_usage, "estimated", False),
                    "provider_usage_version": getattr(
                        token_usage, "provider_usage_version", None
                    ),
                    "pricing_version_id": pricing.pricing_version_id if pricing else None,
                    "cost_microusd": cost.total_microusd if cost else None,
                },
            )
            # A Run cost is publishable only when every model invocation can be
            # priced.  Partial sums look precise while silently undercounting,
            # so one unknown invocation deliberately keeps the Run total NULL.
            connection.execute(
                text(
                    "UPDATE runtime.agent_runs SET total_cost_microusd = ("
                    "SELECT CASE WHEN count(*) = 0 OR count(cost_microusd) <> count(*) "
                    "THEN NULL ELSE sum(cost_microusd) END "
                    "FROM runtime.model_invocations WHERE run_id = :run_id"
                    "), updated_at = now() WHERE run_id = :run_id AND tenant_id = :tenant_id"
                ),
                {
                    "run_id": context.run_id,
                    "tenant_id": context.tenant_id,
                },
            )


def _hash(value: str) -> str:
    return f"sha256:{sha256(value.encode()).hexdigest()}"
