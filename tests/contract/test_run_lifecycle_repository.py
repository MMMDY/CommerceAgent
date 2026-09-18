"""PostgreSQL contracts for durable creation-time run configuration."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from src.models.gateway import ModelDecision
from src.orchestration.router import RouteDecision, RouteOutcome
from src.orchestration.run_creation import ExecutionMode, RunCreationSpec
from src.protocols import (
    Decision,
    DecisionType,
    IntentClassification,
    Message,
    PromptView,
    RiskHint,
    RoutingPromptView,
    RunContext,
    RunStatus,
    TokenUsage,
)
from src.repositories.model_invocations import ModelInvocationRepository
from src.repositories.run_lifecycle import RunLifecycleRepository, RunRoutingRepository


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


def test_create_run_persists_every_execution_pin(engine: Engine) -> None:
    now = datetime.now(UTC)
    conversation_id = uuid4()
    run_id = uuid4()
    tenant_id = f"lifecycle-{uuid4()}"
    deadline = now + timedelta(minutes=7)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversation.conversations "
                "(id, tenant_id, actor_id, client_request_id, status, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :actor_id, :request_id, 'active', :now, :now)"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "actor_id": "lifecycle-actor",
                "request_id": str(uuid4()),
                "now": now,
            },
        )

    repository = RunLifecycleRepository(engine)
    repository.create_run(
        context=RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            actor_id="lifecycle-actor",
            workflow_id="returns",
            workflow_version="1.0",
            status=RunStatus.CREATED,
        ),
        spec=RunCreationSpec(
            execution_mode=ExecutionMode.WORKFLOW,
            policy_version="policy-2026-09",
            model_config_hash="sha256:model-config-v1",
            prompt_version="returns-prompt-1",
            current_step="classify",
            max_steps=5,
            deadline_at=deadline,
        ),
    )

    created = repository.load_definition(run_id=run_id, tenant_id=tenant_id)
    assert created is not None
    assert created.workflow_id == "returns"
    assert created.workflow_version == "1.0"
    assert created.policy_version == "policy-2026-09"
    assert created.model_config_hash == "sha256:model-config-v1"
    assert created.prompt_version == "returns-prompt-1"
    assert created.execution_mode is ExecutionMode.WORKFLOW
    assert created.current_step == "classify"
    assert created.max_steps == 5
    assert created.deadline_at == deadline
    assert repository.load_definition(run_id=run_id, tenant_id="another-tenant") is None


def test_published_v2_does_not_retarget_existing_v1_run(engine: Engine) -> None:
    now = datetime.now(UTC)
    workflow_id = f"version-lock-{uuid4()}"
    conversation_id = uuid4()
    run_id = uuid4()
    tenant_id = f"version-lock-{uuid4()}"
    v1_hash = f"sha256:{uuid4().hex}{uuid4().hex}"
    v2_hash = f"sha256:{uuid4().hex}{uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversation.conversations "
                "(id, tenant_id, actor_id, client_request_id, status, created_at, updated_at) "
                "VALUES (:id, :tenant_id, 'actor', :request_id, 'active', :now, :now)"
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
                "INSERT INTO domain.workflow_versions "
                "(workflow_id, version, definition_json, definition_hash, status, created_at, "
                "activated_at) VALUES (:workflow_id, '1.0', CAST(:definition AS jsonb), "
                ":definition_hash, 'active', :now, :now)"
            ),
            {
                "workflow_id": workflow_id,
                "definition": '{"steps":["v1"]}',
                "definition_hash": v1_hash,
                "now": now,
            },
        )

    repository = RunLifecycleRepository(engine)
    repository.create_run(
        context=RunContext(
            run_id=run_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            actor_id="actor",
            workflow_id=workflow_id,
            workflow_version="1.0",
            status=RunStatus.CREATED,
        ),
        spec=RunCreationSpec(
            execution_mode=ExecutionMode.WORKFLOW,
            policy_version="policy-v1",
            model_config_hash="sha256:model-v1",
            prompt_version="prompt-v1",
            current_step="v1",
            deadline_at=now + timedelta(minutes=5),
        ),
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO domain.workflow_versions "
                "(workflow_id, version, definition_json, definition_hash, status, created_at, "
                "activated_at) VALUES (:workflow_id, '2.0', CAST(:definition AS jsonb), "
                ":definition_hash, 'active', :now, :now)"
            ),
            {
                "workflow_id": workflow_id,
                "definition": '{"steps":["v2"]}',
                "definition_hash": v2_hash,
                "now": now,
            },
        )

    existing = repository.load_definition(run_id=run_id, tenant_id=tenant_id)
    assert existing is not None
    assert existing.workflow_version == "1.0"
    assert existing.current_step == "v1"


def test_pre_route_run_can_be_created_then_selected_by_the_router(engine: Engine) -> None:
    now = datetime.now(UTC)
    tenant_id = f"pre-route-{uuid4()}"
    conversation_id = uuid4()
    context = RunContext(
        run_id=uuid4(),
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        actor_id="route-actor",
        status=RunStatus.CREATED,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversation.conversations "
                "(id, tenant_id, actor_id, client_request_id, status, created_at, updated_at) "
                "VALUES (:id, :tenant_id, 'route-actor', :request_id, 'active', :now, :now)"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "request_id": str(uuid4()),
                "now": now,
            },
        )
    lifecycle = RunLifecycleRepository(engine)
    lifecycle.create_run(
        context=context,
        spec=RunCreationSpec(
            execution_mode=None,
            policy_version="policy-route-v1",
            model_config_hash="sha256:model-route-v1",
            prompt_version="route-prompt-v1",
            current_step="route",
            deadline_at=now + timedelta(minutes=5),
        ),
    )
    pre_route = lifecycle.load_definition(run_id=context.run_id, tenant_id=tenant_id)
    assert pre_route is not None
    assert pre_route.execution_mode is None
    assert pre_route.workflow_id is None

    RunRoutingRepository(engine).select_route(
        context=context,
        decision=RouteDecision(
            outcome=RouteOutcome.EXECUTE,
            execution_mode=ExecutionMode.READONLY_LOOP,
            workflow_id="faq",
            workflow_version="1",
            intent="faq",
            reason_code="ROUTE_RULE_MATCHED",
        ),
    )
    with engine.connect() as connection:
        selected = connection.execute(
            text(
                "SELECT status, execution_mode, workflow_id, workflow_version "
                "FROM runtime.agent_runs WHERE run_id = :run_id"
            ),
            {"run_id": context.run_id},
        ).one()
    assert tuple(selected) == ("running_readonly", "readonly_loop", "faq", "1")


def test_model_invocation_records_actual_gateway_and_prompt_fingerprints(
    engine: Engine,
) -> None:
    now = datetime.now(UTC)
    tenant_id = f"model-audit-{uuid4()}"
    conversation_id = uuid4()
    context = RunContext(
        run_id=uuid4(),
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        actor_id="audit-actor",
        workflow_id="knowledge_query",
        workflow_version="1",
        status=RunStatus.CREATED,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversation.conversations "
                "(id, tenant_id, actor_id, client_request_id, status, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :actor_id, :request_id, 'active', :now, :now)"
            ),
            {
                "id": conversation_id,
                "tenant_id": tenant_id,
                "actor_id": "audit-actor",
                "request_id": str(uuid4()),
                "now": now,
            },
        )
    RunLifecycleRepository(engine).create_run(
        context=context,
        spec=RunCreationSpec(
            execution_mode=ExecutionMode.READONLY_LOOP,
            policy_version="phase2-readonly-v1",
            model_config_hash="sha256:gateway-config",
            prompt_version="prompt-view-v7",
            current_step="retrieve",
            deadline_at=now + timedelta(minutes=5),
        ),
    )
    prompt = PromptView(
        system_policy_version="prompt-view-v7",
        workflow_id="knowledge_query",
        workflow_version="1",
        current_step="retrieve",
        allowed_decisions=("respond",),
        conversation=(),
        known_slots={},
        required_slots=(),
        allowed_tools=(),
        evidence_ids=(),
        remaining_steps=1,
    )
    ModelInvocationRepository(engine).record_success(
        context=context,
        prompt=prompt,
        result=ModelDecision(
            decision=Decision(
                type=DecisionType.RESPOND,
                intent="knowledge_query",
                route="knowledge_query",
                confidence=1,
                response="ok",
            ),
            latency_ms=3,
            token_usage=TokenUsage(
                input_tokens=10,
                output_tokens=4,
                cached_input_tokens=2,
                reasoning_tokens=1,
                total_tokens=14,
            ),
        ),
        provider="fake-provider",
        model="fake-model",
        config_hash="sha256:gateway-config",
    )
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT provider, model, model_config_hash, prompt_version, input_redacted_json, "
                "input_tokens, output_tokens, cached_input_tokens, reasoning_tokens, total_tokens "
                "FROM runtime.model_invocations WHERE run_id = :run_id"
            ),
            {"run_id": context.run_id},
        ).one()
    assert tuple(row[:4]) == (
        "fake-provider",
        "fake-model",
        "sha256:gateway-config",
        "prompt-view-v7",
    )
    assert "conversation" not in row.input_redacted_json
    assert tuple(row[5:]) == (10, 4, 2, 1, 14)

    ModelInvocationRepository(engine).record_classification_success(
        context=context,
        prompt=RoutingPromptView(
            conversation=(Message(role="user", content="查询订单"),),
            allowed_intents=("order_status",),
        ),
        result=IntentClassification(
            intent="order_status",
            risk_hint=RiskHint.READ_ONLY,
            route_hint="order_query",
            confidence=1,
        ),
        provider="fake-provider",
        model="fake-model",
        config_hash="sha256:classifier-config",
        latency_ms=4,
    )
    with engine.connect() as connection:
        classification = connection.execute(
            text(
                "SELECT purpose, model_config_hash, latency_ms, input_redacted_json, "
                "output_redacted_json FROM runtime.model_invocations "
                "WHERE run_id = :run_id AND purpose = 'intent_classification'"
            ),
            {"run_id": context.run_id},
        ).one()
    assert tuple(classification[:3]) == ("intent_classification", "sha256:classifier-config", 4)
    assert "conversation" not in classification.input_redacted_json
    assert classification.output_redacted_json["intent"] == "order_status"
