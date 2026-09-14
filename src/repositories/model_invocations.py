"""Minimal, redacted persistence for model invocations."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from json import dumps
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.models.gateway import ModelDecision
from src.protocols import IntentClassification, PromptView, RoutingPromptView, RunContext


class ModelInvocationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
    ) -> None:
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
                "required_slot_count": len(result.required_slots),
            },
            latency_ms=latency_ms,
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
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO runtime.model_invocations "
                    "(model_call_id, run_id, step_id, purpose, provider, model, "
                    "model_config_hash, prompt_version, input_redacted_json, input_hash, "
                    "output_redacted_json, output_hash, status, error_code, latency_ms, "
                    "started_at, finished_at) "
                    "VALUES (:id, :run_id, :step, :purpose, :provider, :model, :config_hash, "
                    ":prompt_version, CAST(:input AS jsonb), :input_hash, CAST(:output AS jsonb), "
                    ":output_hash, :status, :error_code, :latency, now(), now())"
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
                },
            )


def _hash(value: str) -> str:
    return f"sha256:{sha256(value.encode()).hexdigest()}"
