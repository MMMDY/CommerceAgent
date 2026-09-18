"""Contracts for the immutable Phase 1 PostgreSQL migration chain."""

# ruff: noqa: E501

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from scripts.purge_expired_feedback import purge
from src.db import EXPECTED_ALEMBIC_REVISION
from src.evolution.skill_registry import SkillRegistry
from src.repositories.failures import FailureRepository
from src.repositories.releases import ReleaseRepository
from src.repositories.run_observability import RunObservabilityRepository
from src.repositories.skills import SkillRepository, SkillTransitionError

EXPECTED_TABLES = {
    "conversation": {"conversations", "messages"},
    "runtime": {
        "agent_runs",
        "confirmation_tokens",
        "handoff_tickets",
        "idempotency_records",
        "model_invocations",
        "run_checkpoints",
        "run_events",
        "runtime_outbox",
        "tool_invocations",
    },
    "domain": {"model_pricing_versions", "policy_versions", "workflow_versions"},
    "memory": {"memory_facts"},
    "knowledge": {"knowledge_chunks", "knowledge_documents"},
    "evaluation": {
        "eval_case_results",
        "eval_runs",
        "failure_attributions",
        "failure_cases",
        "judge_results",
    },
    "audit": {"audit_events"},
    "feedback": {"user_feedback"},
    "experience": {"skill_candidates", "skill_versions", "skill_matches", "skill_evaluations", "skill_controls"},
    "release": {
        "releases",
        "release_events",
        "release_assignments",
        "runtime_registrations",
    },
}


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.environ.get("DATABASE_TEST_URL")
    if database_url is None:
        pytest.skip("DATABASE_TEST_URL is required for PostgreSQL contract tests")
    return create_engine(database_url, pool_pre_ping=True)


def test_empty_database_reaches_phase1_head_with_all_expected_tables(engine: Engine) -> None:
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        rows = connection.execute(
            text(
                "SELECT schemaname, tablename FROM pg_tables "
                "WHERE schemaname = ANY(:schemas)"
            ),
            {"schemas": list(EXPECTED_TABLES)},
        ).all()

    actual: dict[str, set[str]] = {schema: set() for schema in EXPECTED_TABLES}
    for schema, table in rows:
        actual[schema].add(table)
    assert revision == EXPECTED_ALEMBIC_REVISION
    assert actual == EXPECTED_TABLES


def test_phase1_uses_postgresql_native_types_and_active_run_constraint(engine: Engine) -> None:
    with engine.connect() as connection:
        types = connection.execute(
            text(
                "SELECT column_name, data_type, udt_name FROM information_schema.columns "
                "WHERE table_schema = 'runtime' AND table_name = 'agent_runs' "
                "AND column_name = ANY(:columns)"
            ),
            {"columns": ["run_id", "deadline_at", "row_version"]},
        ).all()
        payload_type = connection.execute(
            text(
                "SELECT data_type, udt_name FROM information_schema.columns "
                "WHERE table_schema = 'runtime' AND table_name = 'run_events' "
                "AND column_name = 'payload_json'"
            )
        ).one()
        index_definition = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'runtime' "
                "AND indexname = 'uq_agent_runs_active_conversation'"
            )
        ).scalar_one()

    assert {name: (data_type, udt_name) for name, data_type, udt_name in types} == {
        "run_id": ("uuid", "uuid"),
        "deadline_at": ("timestamp with time zone", "timestamptz"),
        "row_version": ("bigint", "int8"),
    }
    assert tuple(payload_type) == ("jsonb", "jsonb")
    assert "WHERE" in index_definition
    for terminal_status in ("completed", "failed", "cancelled", "expired"):
        assert terminal_status in index_definition


def test_failure_retention_contract_preserves_signals_and_blocks_runtime_delete(
    engine: Engine,
) -> None:
    with engine.connect() as connection:
        columns = connection.execute(
            text(
                "SELECT table_schema, table_name, column_name FROM information_schema.columns "
                "WHERE (table_schema, table_name, column_name) IN "
                "(('evaluation', 'failure_cases', 'signals_json'), "
                "('feedback', 'user_feedback', 'correction_hash'))"
            )
        ).all()
        indexes = connection.execute(
            text(
                "SELECT schemaname, indexname FROM pg_indexes WHERE indexname IN "
                "('ix_failure_cases_signal_gin', 'ix_user_feedback_expiry')"
            )
        ).all()
        runtime_can_delete_feedback = connection.execute(
            text(
                "SELECT has_table_privilege(current_user, 'feedback.user_feedback', 'DELETE')"
            )
        ).scalar_one()
        runtime_can_delete_failures = connection.execute(
            text(
                "SELECT has_table_privilege(current_user, 'evaluation.failure_cases', 'DELETE')"
            )
        ).scalar_one()

    assert set(columns) == {
        ("evaluation", "failure_cases", "signals_json"),
        ("feedback", "user_feedback", "correction_hash"),
    }
    assert {name for _, name in indexes} == {
        "ix_failure_cases_signal_gin",
        "ix_user_feedback_expiry",
    }
    assert runtime_can_delete_feedback is False
    assert runtime_can_delete_failures is False


def test_expired_feedback_cleanup_keeps_hash_and_feedback_row(engine: Engine) -> None:
    """Maintenance cleanup removes only consented correction text."""

    tenant_id = "contract-feedback-tenant-" + str(uuid4())
    conversation_id = uuid4()
    run_id = uuid4()
    feedback_id = uuid4()
    now = datetime.now(UTC)
    correction_hash = "sha256:" + "a" * 64
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversation.conversations "
                "(id, tenant_id, actor_id, client_request_id, status, created_at, updated_at) "
                "VALUES (:id, :tenant_id, 'contract-feedback-actor', :request_id, 'active', :now, :now)"
            ),
            {"id": conversation_id, "tenant_id": tenant_id, "request_id": str(uuid4()), "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO runtime.agent_runs "
                "(run_id, conversation_id, tenant_id, actor_ref, status, execution_mode, "
                "workflow_id, workflow_version, policy_version, model_config_hash, prompt_version, "
                "current_step, step_count, max_steps, deadline_at, created_at, updated_at) "
                "VALUES (:run_id, :conversation_id, :tenant_id, 'contract-feedback-actor', "
                "'completed', 'readonly_loop', 'contract', '1.0', 'policy-1.0', 'model-hash', "
                "'prompt-1.0', 'terminal', 1, 6, :deadline_at, :now, :now)"
            ),
            {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "deadline_at": now + timedelta(minutes=5),
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO feedback.user_feedback "
                "(feedback_id, tenant_id, actor_hash, run_id, rating, reason_codes, "
                "correction_redacted, correction_hash, consent_for_improvement, "
                "idempotency_key, expires_at) VALUES "
                "(:feedback_id, :tenant_id, 'sha256:feedback-actor', :run_id, 'down', '[]'::jsonb, "
                "'已脱敏的纠错建议', :correction_hash, true, :idempotency_key, :expires_at)"
            ),
            {
                "feedback_id": feedback_id,
                "tenant_id": tenant_id,
                "run_id": run_id,
                "correction_hash": correction_hash,
                "idempotency_key": "contract-feedback-" + str(feedback_id),
                "expires_at": now - timedelta(seconds=1),
            },
        )

    migration_url = os.environ.get("DATABASE_MIGRATION_URL")
    assert migration_url is not None
    assert purge(database_url=migration_url) >= 1

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT correction_redacted, correction_hash, expires_at "
                "FROM feedback.user_feedback WHERE feedback_id = :feedback_id"
            ),
            {"feedback_id": feedback_id},
        ).one()
        runtime_can_delete = connection.execute(
            text("SELECT has_table_privilege(current_user, 'feedback.user_feedback', 'DELETE')")
        ).scalar_one()
    assert tuple(row) == (None, correction_hash, None)
    assert runtime_can_delete is False


def test_failure_summary_is_tenant_scoped_and_text_free(engine: Engine) -> None:
    repository = FailureRepository(engine)
    tenant_id = "contract-failure-summary-" + str(uuid4())
    repository.record_signal(
        tenant_id=tenant_id,
        signal="run_failed",
        severity="p1",
        source="runtime",
        run_id=None,
        cluster_key="cluster:model-timeout",
        summary_redacted="模型调用失败（脱敏摘要）",
    )
    failure = repository.record_signal(
        tenant_id=tenant_id,
        signal="user_downvote",
        severity="p2",
        source="user_feedback",
        run_id=None,
        cluster_key="cluster:model-timeout",
        summary_redacted="用户反馈未解决问题（脱敏摘要）",
    )
    repository.add_attribution(
        failure_id=failure.failure_id,
        deterministic_category="model_error",
        llm_category=None,
        confidence=None,
        evidence_refs=(),
        model_hash=None,
        prompt_hash=None,
        review_status="pending",
        rationale=None,
    )

    summary = repository.summary(tenant_id=tenant_id, window_days=30)

    assert summary["top_clusters"][0]["cluster_key"] == "cluster:model-timeout"
    assert summary["top_clusters"][0]["case_count"] == 2
    assert summary["taxonomy"][0]["category"] in {"model_error", "unattributed"}
    assert summary["trend"][0]["case_count"] == 2
    assert "summary_redacted" not in str(summary)


def test_learning_summary_is_auditable_and_empty_edges_are_not_inferred(
    engine: Engine,
) -> None:
    tenant_id = "contract-learning-empty-" + str(uuid4())
    summary = FailureRepository(engine).learning_summary(
        tenant_id=tenant_id,
        window_days=30,
    )

    assert summary["clusters"] == []
    stages = summary["stages"]
    assert stages["signals"] == {"case_count": 0, "cluster_count": 0}
    assert stages["clusters"] == {"cluster_count": 0, "eligible_count": 0}
    assert stages["attribution"] == {
        "attributed_case_count": 0,
        "reviewed_case_count": 0,
        "pending_case_count": 0,
    }
    assert stages["skills"] == {
        "candidate_count": 0,
        "pending_review_count": 0,
        "approved_count": 0,
        "blocked_count": 0,
    }
    assert stages["releases"] == {
        "release_count": 0,
        "active_count": 0,
        "canary_count": 0,
        "stopped_or_rolled_back_count": 0,
    }
    assert "summary_redacted" not in str(summary)


def test_learning_summary_links_cluster_to_skill_and_release_by_immutable_ids(
    engine: Engine,
) -> None:
    tenant_id = "contract-learning-chain-" + str(uuid4())
    repository = FailureRepository(engine)
    cluster_key = "cluster:ambiguous-request"
    for index in range(5):
        repository.record_signal(
            tenant_id=tenant_id,
            signal="run_failed",
            severity="p2",
            source="runtime",
            run_id=None,
            case_id=f"case-{index}",
            cluster_key=cluster_key,
            summary_redacted="脱敏失败摘要",
        )
    skill_id = SkillRegistry(engine).generate_from_cluster(
        tenant_id=tenant_id,
        cluster_key=cluster_key,
        scope_type="tenant",
        scope_value=tenant_id,
        keywords=["ambiguous"],
        response_policy="conversational_response",
        offline_gate_pass=True,
        safety_gate_pass=True,
    )
    ReleaseRepository(engine).create(
        tenant_id=tenant_id,
        owner_ref="contract-owner",
        current_version="current-v1",
        candidate_version=str(skill_id),
        gates={},
    )

    summary = repository.learning_summary(tenant_id=tenant_id, window_days=30)
    cluster = summary["clusters"][0]
    skill = cluster["skills"][0]

    assert cluster["cluster_key"] == cluster_key
    assert cluster["max_source_count"] == 1
    assert cluster["evidence_count"] == 5
    assert skill["skill_id"] == str(skill_id)
    assert skill["status"] == "CANDIDATE"
    assert len(skill["releases"]) == 1
    assert skill["releases"][0]["candidate_version"] == str(skill_id)
    assert summary["stages"]["skills"]["candidate_count"] == 1
    assert summary["stages"]["clusters"]["eligible_count"] == 1
    assert summary["stages"]["releases"]["release_count"] == 1


def test_operations_summary_exposes_safety_breakdown_without_false_quality_labels(
    engine: Engine,
) -> None:
    summary = RunObservabilityRepository(engine).operations_summary(
        tenant_id="contract-operations-empty-" + str(uuid4()), window_hours=24
    )

    assert summary["safety_categories"] == []
    assert [item["category"] for item in summary["safety_category_breakdown"]] == [
        "account_takeover",
        "transaction_bypass",
        "privacy",
        "prompt_injection",
        "unknown_tool_state",
    ]
    assert all(item["hit_count"] == 0 for item in summary["safety_category_breakdown"])
    assert summary["safety_trend"] == []
    assert summary["safety_handoff_count"] == 0
    assert summary["safety_false_negative_count"] is None
    assert summary["safety_false_rejection_count"] is None
    assert summary["version_breakdown"] == []


def test_active_workflow_definition_is_immutable_in_postgresql(engine: Engine) -> None:
    workflow_id = f"workflow-{uuid4()}"
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO domain.workflow_versions "
            "(workflow_id, version, definition_json, definition_hash, status, created_at, activated_at) "
            "VALUES (:workflow_id, '1', CAST(:definition AS jsonb), :hash, 'active', now(), now())"),
            {"workflow_id": workflow_id, "definition": '{"step": 1}', "hash": str(uuid4())})
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(text("UPDATE domain.workflow_versions SET definition_json = CAST(:definition AS jsonb) "
                "WHERE workflow_id = :workflow_id AND version = '1'"),
                {"workflow_id": workflow_id, "definition": '{"step": 2}'})


def test_skill_definition_is_immutable_in_postgresql(engine: Engine) -> None:
    skill_id = uuid4()
    version_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO experience.skill_candidates "
                "(skill_id, tenant_id, scope_type, scope_value, trigger_json, strategy_json, "
                "provenance_json, cluster_key, status, source_count, offline_gate_pass, "
                "safety_gate_pass) VALUES (:skill_id, :tenant_id, 'tenant', :scope_value, "
                "'{\"keywords\": [\"contract\"]}'::jsonb, "
                "'{\"response_policy\": \"conversational_response\"}'::jsonb, "
                "'{}'::jsonb, :cluster_key, 'CANDIDATE', 5, true, true)"
            ),
            {
                "skill_id": skill_id,
                "tenant_id": "contract-tenant-" + str(skill_id),
                "scope_value": "contract-scope-" + str(skill_id),
                "cluster_key": "contract-cluster-" + str(skill_id),
            },
        )
        connection.execute(
            text(
                "INSERT INTO experience.skill_versions "
                "(skill_version_id, skill_id, version_no, definition_json, definition_hash, "
                "expires_at, status) VALUES (:version_id, :skill_id, 1, "
                "'{\"trigger\": {}, \"response_policy\": \"conversational_response\", "
                "\"scope\": {\"type\": \"tenant\", \"value\": \"tenant\"}, "
                "\"positive_examples\": [\"positive\"], \"negative_examples\": [\"negative\"], "
                "\"forbidden_tools\": [\"business_write_tools\"], \"ttl_seconds\": 2592000}'::jsonb, "
                ":definition_hash, now() + interval '1 day', 'PENDING_REVIEW')"
            ),
            {"version_id": version_id, "skill_id": skill_id, "definition_hash": str(uuid4())},
        )
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE experience.skill_versions SET definition_json = '{\"changed\": true}'::jsonb "
                    "WHERE skill_version_id = :version_id"
                ),
                {"version_id": version_id},
            )


def test_skill_contract_guards_and_global_scope_are_database_enforced(engine: Engine) -> None:
    with engine.connect() as connection:
        columns = connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'experience' AND table_name = 'skill_candidates' "
                "AND column_name IN ('owner', 'kind')"
            )
        ).scalars().all()
        constraints = connection.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conname IN ('skill_candidates_json_contract', "
                "'skill_candidates_global_scope_guard', 'skill_versions_json_contract')"
            )
        ).scalars().all()

    assert set(columns) == {"owner", "kind"}
    assert set(constraints) == {
        "skill_candidates_json_contract",
        "skill_candidates_global_scope_guard",
        "skill_versions_json_contract",
    }

    with pytest.raises(DBAPIError, match="skill_candidates_global_scope_guard"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO experience.skill_candidates "
                    "(skill_id, tenant_id, scope_type, scope_value, trigger_json, strategy_json, "
                    "provenance_json, cluster_key, status, source_count, offline_gate_pass, "
                    "safety_gate_pass) VALUES (:skill_id, :tenant_id, 'global', '*', "
                    "'{\"keywords\": [\"contract\"]}'::jsonb, "
                    "'{\"response_policy\": \"safety_deescalation\"}'::jsonb, '{}', "
                    ":cluster_key, 'CANDIDATE', 5, true, true)"
                ),
                {
                    "skill_id": uuid4(),
                    "tenant_id": "contract-global-guard",
                    "cluster_key": "contract-global-guard-" + str(uuid4()),
                },
            )

    skill_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO experience.skill_candidates "
                "(skill_id, tenant_id, scope_type, scope_value, trigger_json, strategy_json, "
                "provenance_json, cluster_key, status, source_count, offline_gate_pass, "
                "safety_gate_pass) VALUES (:skill_id, :tenant_id, 'tenant', 'guard', "
                "'{\"keywords\": [\"contract\"]}'::jsonb, "
                "'{\"response_policy\": \"conversational_response\"}'::jsonb, '{}', "
                ":cluster_key, 'CANDIDATE', 5, true, true)"
            ),
            {
                "skill_id": skill_id,
                "tenant_id": "contract-version-guard",
                "cluster_key": "contract-version-guard-" + str(uuid4()),
            },
        )
    with pytest.raises(DBAPIError, match="skill_versions_json_contract"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO experience.skill_versions "
                    "(skill_version_id, skill_id, version_no, definition_json, definition_hash, "
                    "expires_at, status) VALUES (:version_id, :skill_id, 1, '{}', :hash, "
                    "now() + interval '1 day', 'PENDING_REVIEW')"
                ),
                {"version_id": uuid4(), "skill_id": skill_id, "hash": str(uuid4())},
            )


def test_skill_evaluation_persists_only_bounded_paired_aggregates(engine: Engine) -> None:
    skill_id = uuid4()
    version_id = uuid4()
    tenant_id = "contract-eval-tenant-" + str(skill_id)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO experience.skill_candidates "
                "(skill_id, tenant_id, scope_type, scope_value, trigger_json, strategy_json, "
                "provenance_json, cluster_key, status, source_count, offline_gate_pass, "
                "safety_gate_pass) VALUES (:skill_id, :tenant_id, 'tenant', :scope_value, "
                "'{\"keywords\": [\"contract\"]}'::jsonb, "
                "'{\"response_policy\": \"conversational_response\"}'::jsonb, "
                "'{}'::jsonb, :cluster_key, 'CANDIDATE', 5, true, true)"
            ),
            {
                "skill_id": skill_id,
                "tenant_id": tenant_id,
                "scope_value": "contract-eval-scope-" + str(skill_id),
                "cluster_key": "contract-eval-cluster-" + str(skill_id),
            },
        )
        connection.execute(
            text(
                "INSERT INTO experience.skill_versions "
                "(skill_version_id, skill_id, version_no, definition_json, definition_hash, "
                "expires_at, status) VALUES (:version_id, :skill_id, 1, "
                "'{\"trigger\": {}, \"response_policy\": \"conversational_response\", "
                "\"scope\": {\"type\": \"tenant\", \"value\": \"tenant\"}, "
                "\"positive_examples\": [\"positive\"], \"negative_examples\": [\"negative\"], "
                "\"forbidden_tools\": [\"business_write_tools\"], \"ttl_seconds\": 2592000}'::jsonb, "
                ":definition_hash, now() + interval '1 day', 'PENDING_REVIEW')"
            ),
            {"version_id": version_id, "skill_id": skill_id, "definition_hash": str(uuid4())},
        )

    repository = SkillRepository(engine)
    recorded = repository.record_evaluation(
        tenant_id=tenant_id,
        skill_id=skill_id,
        skill_version_id=version_id,
        dataset_hash="sha256:" + "b" * 64,
        before={"quality": 0.70, "p95_latency_ms": 120},
        after={"quality": 0.82, "p95_latency_ms": 108},
        safety_result="pass",
        cost_delta_microusd=-3,
        latency_delta_ms=-12,
        gate_pass=True,
        judge_disagreement_count=0,
    )
    assert recorded["skill_version_id"] == str(version_id)
    assert repository.get(tenant_id=tenant_id, skill_id=skill_id)["evaluations"][0]["before"] == {
        "quality": 0.7,
        "p95_latency_ms": 120,
    }
    listed = repository.list(tenant_id=tenant_id)
    assert listed[0]["evaluation_gate_pass"] is True
    assert listed[0]["evaluation_safety_result"] == "pass"
    assert listed[0]["evaluation_judge_disagreement_count"] == 0

    with pytest.raises(SkillTransitionError, match="disagreement"):
        repository.record_evaluation(
            tenant_id=tenant_id,
            skill_id=skill_id,
            dataset_hash="sha256:" + "c" * 64,
            before={"quality": 0.70},
            after={"quality": 0.80},
            safety_result="pass",
            cost_delta_microusd=0,
            latency_delta_ms=0,
            gate_pass=True,
            judge_disagreement_count=1,
        )


def test_skill_kill_switch_is_tenant_scoped_and_reversible(engine: Engine) -> None:
    tenant_id = "contract-skill-control-" + str(uuid4())
    repository = SkillRepository(engine)

    assert repository.matching_enabled(tenant_id=tenant_id) is True
    initial = repository.matching_control(tenant_id=tenant_id)
    assert initial["tenant_id"] == tenant_id
    assert initial["matching_enabled"] is True
    assert initial["reason_hash"] is None
    disabled = repository.set_matching_enabled(
        tenant_id=tenant_id,
        enabled=False,
        updated_by="contract-approver",
        reason_hash="sha256:" + "a" * 64,
    )
    assert disabled["matching_enabled"] is False
    assert repository.matching_enabled(tenant_id=tenant_id) is False
    control = repository.matching_control(tenant_id=tenant_id)
    assert control["matching_enabled"] is False
    assert str(control["reason_hash"]).startswith("sha256:")
    assert repository.matching_enabled(tenant_id=tenant_id + "-other") is True

    enabled = repository.set_matching_enabled(
        tenant_id=tenant_id,
        enabled=True,
        updated_by="contract-approver",
        reason_hash="sha256:" + "b" * 64,
    )
    assert enabled["matching_enabled"] is True
