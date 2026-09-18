"""PostgreSQL contract for durable Shadow/Canary assignment evidence."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from src.protocols import RequestRiskLevel
from src.release.canary_guard import CanaryMetrics
from src.release.progressive_delivery import assign_traffic
from src.repositories.releases import ReleaseRepository, ReleaseTransitionError


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


def test_release_assignment_is_idempotent_and_tenant_bound(engine: Engine) -> None:
    tenant_id = "assignment-tenant-" + uuid4().hex
    actor_id = "assignment-actor"
    conversation_id = uuid4()
    run_id = uuid4()
    now = datetime.now(UTC)
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
                "actor_id": actor_id,
                "request_id": str(uuid4()),
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO runtime.agent_runs "
                "(run_id, conversation_id, tenant_id, actor_ref, status, execution_mode, "
                "workflow_id, workflow_version, policy_version, model_config_hash, prompt_version, "
                "current_step, step_count, max_steps, deadline_at, accepted_at, created_at, "
                "updated_at) "
                "VALUES (:run_id, :conversation_id, :tenant_id, :actor_ref, 'created', "
                "'readonly_loop', 'catalog_query', '1', 'policy', 'model', 'prompt', 'route', "
                "0, 6, "
                ":deadline, :now, :now, :now)"
            ),
            {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "actor_ref": actor_id,
                "deadline": now + timedelta(minutes=5),
                "now": now,
            },
        )

    repository = ReleaseRepository(engine)
    release = repository.create(
        tenant_id=tenant_id,
        owner_ref="admin",
        current_version="current-v1",
        candidate_version="candidate-v2",
        gates={},
    )
    assignment = assign_traffic(
        tenant_id=tenant_id,
        actor_id=actor_id,
        run_id=str(run_id),
        conversation_id=str(conversation_id),
        current_version="current-v1",
        candidate_version="candidate-v2",
        stage="SHADOW",
        status="ACTIVE",
        risk_level=RequestRiskLevel.LOW,
    )
    first = repository.record_assignment(
        tenant_id=tenant_id,
        release_id=release["release_id"],
        run_id=run_id,
        actor_id=actor_id,
        conversation_id=conversation_id,
        assignment=assignment,
        risk_level=RequestRiskLevel.LOW.value,
        risk_hint="read_only",
        comparison={"route": "catalog_query"},
    )
    second = repository.record_assignment(
        tenant_id=tenant_id,
        release_id=release["release_id"],
        run_id=run_id,
        actor_id=actor_id,
        conversation_id=conversation_id,
        assignment=assignment,
        risk_level=RequestRiskLevel.LOW.value,
        risk_hint="read_only",
    )

    assert first == second
    repository.record_assignment(
        tenant_id=tenant_id,
        release_id=release["release_id"],
        run_id=run_id,
        actor_id=actor_id,
        conversation_id=conversation_id,
        assignment=assignment,
        risk_level=RequestRiskLevel.LOW.value,
        risk_hint="read_only",
        comparison={
            "current_route": "catalog_query",
            "candidate_route": "conversational_response",
            "current_skill": None,
            "candidate_skill": "skill-v2",
            "estimated_cost_delta_microusd": None,
        },
    )
    detail = repository.get(tenant_id=tenant_id, release_id=release["release_id"])
    assert detail is not None
    assert len(detail["assignments"]) == 1
    assert detail["assignments"][0]["mode"] == "shadow"
    assert detail["assignments"][0]["comparison"]["candidate_skill"] == "skill-v2"
    assert "actor" not in detail["assignments"][0]
    assert not repository.runtime_available(
        tenant_id=tenant_id, version="candidate-v2"
    )
    registration = repository.register_runtime(
        tenant_id=tenant_id,
        version="candidate-v2",
        runtime_hash="sha256:candidate-v2",
        metadata={"kind": "contract"},
    )
    assert registration["status"] == "ACTIVE"
    assert repository.runtime_available(tenant_id=tenant_id, version="candidate-v2")
    assert repository.register_runtime(
        tenant_id=tenant_id,
        version="candidate-v2",
        runtime_hash="sha256:candidate-v2",
        metadata={"kind": "contract-refresh"},
    )["registration_id"] == registration["registration_id"]
    with pytest.raises(ReleaseTransitionError, match="runtime_definition_conflict"):
        repository.register_runtime(
            tenant_id=tenant_id,
            version="candidate-v2",
            runtime_hash="sha256:changed",
        )
    blocked_release = repository.create(
        tenant_id=tenant_id,
        owner_ref="admin",
        current_version="current-v1",
        candidate_version="candidate-unregistered",
        gates={},
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE release.releases SET observation_ends_at = now() - interval '1 minute' "
                "WHERE release_id = :release_id"
            ),
            {"release_id": blocked_release["release_id"]},
        )
    with pytest.raises(ReleaseTransitionError, match="candidate_runtime_unavailable"):
        repository.evaluate_and_advance(
            tenant_id=tenant_id,
            release_id=blocked_release["release_id"],
            actor_ref="admin",
            metrics=CanaryMetrics(terminal_response_coverage=1.0),
        )
    metrics = repository.canary_metrics(
        tenant_id=tenant_id, release_id=release["release_id"]
    )
    assert metrics.p0_events == 0
    assert metrics.terminal_response_coverage == 0.0
