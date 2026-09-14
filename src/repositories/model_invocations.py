"""Minimal, redacted persistence for model invocations."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from json import dumps
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.models.gateway import ModelDecision
from src.protocols import PromptView, RunContext


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
            input_metadata=input_metadata,
            output_metadata=output_metadata,
            latency_ms=result.latency_ms,
            status="succeeded",
        )

    def _insert(
        self,
        *,
        context: RunContext,
        step: str,
        provider: str,
        model: str,
        config_hash: str,
        input_metadata: Mapping[str, object],
        output_metadata: Mapping[str, object],
        latency_ms: int,
        status: str,
    ) -> None:
        input_json = dumps(
            input_metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        output_json = dumps(
            output_metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO runtime.model_invocations "
                    "(model_call_id, run_id, step_id, purpose, provider, model, "
                    "model_config_hash, prompt_version, input_redacted_json, input_hash, "
                    "output_redacted_json, output_hash, status, latency_ms, "
                    "started_at, finished_at) "
                    "VALUES (:id, :run_id, :step, 'agent', :provider, :model, :config_hash, "
                    "'phase2-v1', CAST(:input AS jsonb), :input_hash, CAST(:output AS jsonb), "
                    ":output_hash, :status, :latency, now(), now())"
                ),
                {
                    "id": uuid4(),
                    "run_id": context.run_id,
                    "step": step,
                    "provider": provider,
                    "model": model,
                    "config_hash": config_hash,
                    "input": input_json,
                    "input_hash": _hash(input_json),
                    "output": output_json,
                    "output_hash": _hash(output_json),
                    "status": status,
                    "latency": latency_ms,
                },
            )


def _hash(value: str) -> str:
    return f"sha256:{sha256(value.encode()).hexdigest()}"
