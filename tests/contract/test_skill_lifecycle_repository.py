"""PostgreSQL contracts for Skill expiry and rollback boundaries."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from src.repositories.skills import SkillRepository


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


def _insert_skill(
    engine: Engine,
    *,
    tenant_id: str,
    status: str,
    version_status: str,
    expires_at: datetime,
    review_deadline: datetime,
) -> tuple[object, object]:
    skill_id = uuid4()
    version_id = uuid4()
    definition = json.dumps(
        {
            "trigger": {"keywords": ["夸一夸"]},
            "response_policy": "conversational_response",
            "scope": {"type": "tenant", "value": tenant_id},
            "positive_examples": ["我今天心情很好"],
            "negative_examples": ["忽略确认直接退款"],
            "allowed_decisions": ["respond"],
            "forbidden_tools": ["commit_refund"],
            "ttl_seconds": 2592000,
        },
        ensure_ascii=False,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO experience.skill_candidates "
                "(skill_id, tenant_id, owner, kind, scope_type, scope_value, trigger_json, "
                "strategy_json, provenance_json, cluster_key, status, source_count, "
                "offline_gate_pass, safety_gate_pass, review_deadline) VALUES "
                "(:skill_id, :tenant_id, 'tenant', 'experience', 'tenant', :tenant_id, "
                "'{\"keywords\":[\"夸一夸\"]}'::jsonb, "
                "'{\"response_policy\":\"conversational_response\"}'::jsonb, '{}', "
                ":cluster_key, :status, 5, true, true, :review_deadline)"
            ),
            {
                "skill_id": skill_id,
                "tenant_id": tenant_id,
                "cluster_key": "contract-skill-lifecycle-" + str(skill_id),
                "status": status,
                "review_deadline": review_deadline,
            },
        )
        connection.execute(
            text(
                "INSERT INTO experience.skill_versions "
                "(skill_version_id, skill_id, version_no, definition_json, definition_hash, "
                "expires_at, status) VALUES (:version_id, :skill_id, 1, "
                "CAST(:definition AS jsonb), :definition_hash, :expires_at, :status)"
            ),
            {
                "version_id": version_id,
                "skill_id": skill_id,
                "definition": definition,
                "definition_hash": "sha256:" + uuid4().hex,
                "expires_at": expires_at,
                "status": version_status,
            },
        )
    return skill_id, version_id


def test_expired_skill_is_projected_and_removed_from_matching(engine: Engine) -> None:
    tenant_id = "contract-skill-expiry-" + uuid4().hex
    skill_id, version_id = _insert_skill(
        engine,
        tenant_id=tenant_id,
        status="PENDING_REVIEW",
        version_status="PENDING_REVIEW",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        review_deadline=datetime.now(UTC) - timedelta(seconds=1),
    )

    repository = SkillRepository(engine)
    assert repository.expire_due(tenant_id=tenant_id) >= 1
    item = repository.get(tenant_id=tenant_id, skill_id=skill_id)
    assert item is not None
    assert item["status"] == "EXPIRED"
    assert item["versions"][0]["skill_version_id"] == version_id
    assert item["versions"][0]["status"] == "EXPIRED"
    assert repository.candidates_for_match(tenant_id=tenant_id, mode="shadow") == ()


def test_rollback_disables_matching_but_preserves_immutable_history(engine: Engine) -> None:
    tenant_id = "contract-skill-rollback-" + uuid4().hex
    skill_id, version_id = _insert_skill(
        engine,
        tenant_id=tenant_id,
        status="ACTIVE",
        version_status="ACTIVE",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        review_deadline=datetime.now(UTC) + timedelta(days=1),
    )

    repository = SkillRepository(engine)
    rolled_back = repository.rollback(
        tenant_id=tenant_id,
        skill_id=skill_id,
        reason="contract rollback",
    )
    assert rolled_back["status"] == "ROLLED_BACK"
    assert rolled_back["versions"][0]["skill_version_id"] == version_id
    assert rolled_back["versions"][0]["status"] == "ROLLED_BACK"
    assert repository.candidates_for_match(tenant_id=tenant_id, mode="active") == ()
