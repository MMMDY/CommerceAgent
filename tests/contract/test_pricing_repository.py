"""PostgreSQL contract for immutable, time-bounded pricing lookup."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from src.models.gateway import ModelDecision
from src.protocols import Decision, DecisionType, PromptView, RunContext, RunStatus, TokenUsage
from src.repositories.model_invocations import ModelInvocationRepository
from src.repositories.pricing import PricingRepository


@pytest.fixture(scope="module")
def runtime_engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


@pytest.fixture(scope="module")
def migration_engine() -> Engine:
    database_url = os.environ.get("DATABASE_MIGRATION_URL")
    if database_url is None:
        pytest.skip("DATABASE_MIGRATION_URL is required for pricing setup")
    return create_engine(database_url, pool_pre_ping=True)


def test_pricing_lookup_is_time_bounded_and_runtime_readable(
    runtime_engine: Engine, migration_engine: Engine
) -> None:
    provider = f"pricing-provider-{uuid4()}"
    model = f"pricing-model-{uuid4()}"
    pricing_id = uuid4()
    now = datetime.now(UTC)
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO domain.model_pricing_versions "
                "(pricing_version_id, provider, model, effective_from, effective_to, "
                "input_per_million, cached_input_per_million, output_per_million, "
                "reasoning_per_million, currency, source, refreshed_at, definition_hash) "
                "VALUES (:id, :provider, :model, :starts, :ends, :input, :cached, :output, "
                ":reasoning, 'USD', 'contract-test', :refreshed, :hash)"
            ),
            {
                "id": pricing_id,
                "provider": provider,
                "model": model,
                "starts": now - timedelta(minutes=1),
                "ends": now + timedelta(minutes=1),
                "input": Decimal("0.50"),
                "cached": Decimal("0.10"),
                "output": Decimal("1.00"),
                "reasoning": Decimal("2.00"),
                "refreshed": now,
                "hash": f"contract-{uuid4()}",
            },
        )

    found = PricingRepository(runtime_engine).find(
        provider=provider, model=model, at=now
    )
    assert found is not None
    assert found.pricing_version_id == str(pricing_id)
    assert found.input_per_million == Decimal("0.50")
    assert PricingRepository(runtime_engine).find(
        provider=provider, model=model, at=now + timedelta(hours=1)
    ) is None

    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM domain.model_pricing_versions "
                "WHERE pricing_version_id = :pricing_id"
            ),
            {"pricing_id": pricing_id},
        )


def test_model_invocation_persists_usage_and_cost_snapshot(
    runtime_engine: Engine, migration_engine: Engine
) -> None:
    provider = f"cost-provider-{uuid4()}"
    model = f"cost-model-{uuid4()}"
    pricing_id = uuid4()
    conversation_id = uuid4()
    run_id = uuid4()
    tenant_id = f"cost-tenant-{uuid4()}"
    now = datetime.now(UTC)
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO domain.model_pricing_versions "
                "(pricing_version_id, provider, model, effective_from, input_per_million, "
                "output_per_million, currency, source, refreshed_at, definition_hash) "
                "VALUES (:id, :provider, :model, :starts, :input, :output, 'USD', "
                "'contract-test', :refreshed, :hash)"
            ),
            {
                "id": pricing_id,
                "provider": provider,
                "model": model,
                "starts": now - timedelta(minutes=1),
                "input": Decimal("0.50"),
                "output": Decimal("1.00"),
                "refreshed": now,
                "hash": f"cost-contract-{uuid4()}",
            },
        )
        connection.execute(
            text(
                "INSERT INTO conversation.conversations "
                "(id, tenant_id, actor_id, client_request_id, status, created_at, updated_at) "
                "VALUES (:id, :tenant_id, 'cost-actor', :request_id, 'active', :now, :now)"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "request_id": str(uuid4()),
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO runtime.agent_runs "
                "(run_id, conversation_id, tenant_id, actor_ref, status, execution_mode, "
                "workflow_id, workflow_version, policy_version, model_config_hash, prompt_version, "
                "current_step, step_count, max_steps, deadline_at, created_at, updated_at) "
                "VALUES (:run_id, :conversation_id, :tenant_id, 'cost-actor', 'running_readonly', "
                "'readonly_loop', 'cost', '1.0', 'policy', 'model', 'prompt', 'answer', 0, 6, "
                ":deadline, :now, :now)"
            ),
            {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "deadline": now + timedelta(minutes=5),
                "now": now,
            },
        )

    try:
        ModelInvocationRepository(runtime_engine).record_success(
            context=RunContext(
                run_id=run_id,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                actor_id="cost-actor",
                status=RunStatus.RUNNING_READONLY,
            ),
            prompt=PromptView(
                system_policy_version="policy",
                workflow_id="cost",
                workflow_version="1.0",
                current_step="answer",
                allowed_decisions=("respond",),
                conversation=(),
                known_slots={},
                required_slots=(),
                allowed_tools=(),
                evidence_ids=(),
                remaining_steps=1,
            ),
            result=ModelDecision(
                decision=Decision(
                    type=DecisionType.RESPOND,
                    intent="cost",
                    route="cost",
                    confidence=1,
                    response="ok",
                ),
                latency_ms=7,
                token_usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            ),
            provider=provider,
            model=model,
            config_hash="sha256:cost-contract",
        )
        with runtime_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT input_tokens, output_tokens, total_tokens, usage_estimated, "
                    "pricing_version_id, cost_microusd FROM runtime.model_invocations "
                    "WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            ).one()
            run_cost = connection.execute(
                text(
                    "SELECT total_cost_microusd FROM runtime.agent_runs "
                    "WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            ).scalar_one()
        assert tuple(row) == (100, 50, 150, False, pricing_id, 100)
        assert run_cost == 100
    finally:
        with migration_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM runtime.model_invocations WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
            connection.execute(
                text("DELETE FROM runtime.agent_runs WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
            connection.execute(
                text("DELETE FROM conversation.conversations WHERE id = :conversation_id"),
                {"conversation_id": conversation_id},
            )
            connection.execute(
                text(
                    "DELETE FROM domain.model_pricing_versions "
                    "WHERE pricing_version_id = :pricing_id"
                ),
                {"pricing_id": pricing_id},
            )
