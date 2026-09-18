from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from src.repositories.feedback import FeedbackRepository


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = os.environ.get("DATABASE_TEST_URL")
    if url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(url, pool_pre_ping=True)


def test_feedback_consent_sanitization_ttl_and_idempotency(engine: Engine) -> None:
    tenant_id = "feedback-contract-" + uuid4().hex
    conversation_id, run_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversation.conversations "
                "(id, tenant_id, actor_id, client_request_id, status, created_at, updated_at) "
                "VALUES (:id, :tenant_id, 'feedback-owner', :request_id, 'active', :now, :now)"
            ),
            {"id": conversation_id, "tenant_id": tenant_id, "request_id": str(uuid4()), "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO runtime.agent_runs "
                "(run_id, conversation_id, tenant_id, actor_ref, status, execution_mode, "
                "workflow_id, workflow_version, policy_version, model_config_hash, prompt_version, "
                "current_step, step_count, max_steps, deadline_at, created_at, updated_at) "
                "VALUES (:run_id, :conversation_id, :tenant_id, 'feedback-owner', 'completed', "
                "'readonly_loop', 'contract', '1', 'policy', 'model', 'prompt', 'terminal', 1, 6, "
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

    repository = FeedbackRepository(engine)
    without_consent = repository.submit(
        tenant_id=tenant_id,
        actor_id="feedback-owner",
        run_id=run_id,
        rating="down",
        reason_codes=("wrong_answer",),
        correction="手机号 13812345678 不应落库",
        consent_for_improvement=False,
        idempotency_key="feedback-no-consent",
    )
    assert without_consent.correction_redacted is None
    assert without_consent.correction_hash is None

    first = repository.submit(
        tenant_id=tenant_id,
        actor_id="feedback-owner",
        run_id=run_id,
        rating="down",
        reason_codes=("wrong_answer",),
        correction="邮箱 user@example.com 请修正",
        consent_for_improvement=True,
        idempotency_key="feedback-consented",
    )
    replay = repository.submit(
        tenant_id=tenant_id,
        actor_id="feedback-owner",
        run_id=run_id,
        rating="up",
        reason_codes=(),
        correction="different payload",
        consent_for_improvement=False,
        idempotency_key="feedback-consented",
    )
    assert replay.feedback_id == first.feedback_id
    assert first.correction_redacted is not None
    assert "user@example.com" not in first.correction_redacted
    assert first.correction_hash is not None
    assert first.expires_at is not None
    assert first.expires_at <= now + timedelta(days=30, minutes=1)
    assert "feedback-owner" not in first.actor_hash

