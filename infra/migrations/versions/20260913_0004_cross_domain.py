"""Create cross-domain persistence tables used by Phase 1 contracts.

Revision ID: 20260913_0004
Revises: 20260913_0003
"""

from alembic import op

revision = "20260913_0004"
down_revision = "20260913_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE runtime.tool_invocations (
            tool_call_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runtime.agent_runs(run_id),
            step_id varchar(64) NOT NULL, tool_name varchar(80) NOT NULL, tool_version varchar(32) NOT NULL,
            risk_level varchar(16) NOT NULL, arguments_redacted_json jsonb NOT NULL, arguments_hash varchar(80) NOT NULL,
            status varchar(24) NOT NULL, attempt_no integer NOT NULL, idempotency_record_id uuid NULL,
            result_redacted_json jsonb NULL, result_hash varchar(80) NULL, error_code varchar(64) NULL,
            started_at timestamptz NOT NULL, finished_at timestamptz NULL, latency_ms bigint NULL
        );
        CREATE TABLE runtime.model_invocations (
            model_call_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runtime.agent_runs(run_id),
            step_id varchar(64) NOT NULL, purpose varchar(32) NOT NULL, provider varchar(64) NOT NULL,
            model varchar(128) NOT NULL, model_config_hash varchar(80) NOT NULL, prompt_version varchar(64) NOT NULL,
            input_redacted_json jsonb NOT NULL, input_hash varchar(80) NOT NULL, output_redacted_json jsonb NULL,
            output_hash varchar(80) NULL, status varchar(24) NOT NULL, error_code varchar(64) NULL,
            input_tokens bigint NULL, output_tokens bigint NULL, latency_ms bigint NULL,
            started_at timestamptz NOT NULL, finished_at timestamptz NULL
        );
        CREATE TABLE domain.workflow_versions (
            workflow_id varchar(64) NOT NULL, version varchar(32) NOT NULL, definition_json jsonb NOT NULL,
            definition_hash varchar(80) NOT NULL UNIQUE, status varchar(16) NOT NULL,
            created_at timestamptz NOT NULL, activated_at timestamptz NULL, PRIMARY KEY (workflow_id, version)
        );
        CREATE TABLE domain.policy_versions (
            policy_id varchar(64) NOT NULL, version varchar(32) NOT NULL, rules_json jsonb NOT NULL,
            rules_hash varchar(80) NOT NULL UNIQUE, effective_from timestamptz NOT NULL, effective_to timestamptz NULL,
            status varchar(16) NOT NULL, created_at timestamptz NOT NULL, PRIMARY KEY (policy_id, version)
        );
        CREATE TABLE memory.memory_facts (
            fact_id uuid PRIMARY KEY, tenant_id varchar(64) NOT NULL, actor_ref varchar(128) NOT NULL,
            fact_type varchar(64) NOT NULL, value_json jsonb NOT NULL, source_type varchar(24) NOT NULL,
            source_ref varchar(64) NOT NULL, confidence numeric(5,4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            observed_at timestamptz NOT NULL, valid_until timestamptz NULL, supersedes_fact_id uuid NULL,
            status varchar(16) NOT NULL, created_at timestamptz NOT NULL
        );
        CREATE TABLE knowledge.knowledge_documents (
            document_id uuid PRIMARY KEY, tenant_id varchar(64) NOT NULL, topic varchar(128) NOT NULL,
            product_ref varchar(128) NULL, region varchar(64) NULL, version varchar(32) NOT NULL,
            effective_from timestamptz NOT NULL, effective_to timestamptz NULL, access_level varchar(32) NOT NULL,
            source_uri varchar(500) NOT NULL, content_hash varchar(80) NOT NULL, status varchar(16) NOT NULL
        );
        CREATE TABLE knowledge.knowledge_chunks (
            chunk_id uuid PRIMARY KEY, document_id uuid NOT NULL REFERENCES knowledge.knowledge_documents(document_id),
            chunk_no integer NOT NULL, text_redacted text NOT NULL, text_hash varchar(80) NOT NULL,
            metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb, embedding_ref varchar(256) NULL,
            index_version varchar(32) NOT NULL, created_at timestamptz NOT NULL,
            UNIQUE (document_id, chunk_no, index_version)
        );
        CREATE TABLE evaluation.eval_runs (
            eval_run_id uuid PRIMARY KEY, dataset_hash varchar(80) NOT NULL, rubric_version varchar(64) NOT NULL,
            status varchar(24) NOT NULL, config_json jsonb NOT NULL, created_at timestamptz NOT NULL, finished_at timestamptz NULL
        );
        CREATE TABLE evaluation.eval_case_results (
            eval_run_id uuid NOT NULL REFERENCES evaluation.eval_runs(eval_run_id), case_id varchar(128) NOT NULL,
            track varchar(64) NOT NULL, hard_pass boolean NOT NULL, result_json jsonb NOT NULL,
            created_at timestamptz NOT NULL, PRIMARY KEY (eval_run_id, case_id)
        );
        CREATE TABLE evaluation.judge_results (
            eval_run_id uuid NOT NULL, case_id varchar(128) NOT NULL, judge_model varchar(128) NOT NULL,
            score numeric(4,2) NULL, result_json jsonb NOT NULL, self_judged boolean NOT NULL,
            created_at timestamptz NOT NULL, PRIMARY KEY (eval_run_id, case_id),
            FOREIGN KEY (eval_run_id, case_id) REFERENCES evaluation.eval_case_results(eval_run_id, case_id)
        );
        CREATE TABLE audit.audit_events (
            audit_event_id uuid PRIMARY KEY, tenant_id varchar(64) NULL, actor_ref varchar(128) NULL,
            event_type varchar(64) NOT NULL, payload_redacted_json jsonb NOT NULL, payload_hash varchar(80) NOT NULL,
            created_at timestamptz NOT NULL
        );
        GRANT USAGE ON SCHEMA domain, memory, knowledge, evaluation, audit TO commerce_agent_runtime;
        GRANT SELECT, INSERT, UPDATE ON runtime.tool_invocations, runtime.model_invocations,
          domain.workflow_versions, domain.policy_versions, memory.memory_facts,
          knowledge.knowledge_documents, knowledge.knowledge_chunks, evaluation.eval_runs,
          evaluation.eval_case_results, evaluation.judge_results, audit.audit_events TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    for table in (
        "audit.audit_events",
        "evaluation.judge_results",
        "evaluation.eval_case_results",
        "evaluation.eval_runs",
        "knowledge.knowledge_chunks",
        "knowledge.knowledge_documents",
        "memory.memory_facts",
        "domain.policy_versions",
        "domain.workflow_versions",
        "runtime.model_invocations",
        "runtime.tool_invocations",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
