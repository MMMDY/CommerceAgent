"""Persist consented feedback, failure cases and attribution evidence."""

from alembic import op

revision = "20260917_0016"
down_revision = "20260917_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS feedback;
        CREATE TABLE IF NOT EXISTS feedback.user_feedback (
            feedback_id uuid PRIMARY KEY,
            tenant_id varchar(64) NOT NULL,
            actor_hash varchar(80) NOT NULL,
            run_id uuid NOT NULL REFERENCES runtime.agent_runs(run_id),
            rating varchar(8) NOT NULL CHECK (rating IN ('up', 'down')),
            reason_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
            correction_redacted text NULL CHECK (correction_redacted IS NULL OR length(correction_redacted) <= 2000),
            consent_for_improvement boolean NOT NULL DEFAULT false,
            idempotency_key varchar(128) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NULL,
            UNIQUE (tenant_id, actor_hash, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS ix_user_feedback_run_created
          ON feedback.user_feedback (tenant_id, run_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS evaluation.failure_cases (
            failure_id uuid PRIMARY KEY,
            tenant_id varchar(64) NOT NULL,
            signal varchar(64) NOT NULL,
            severity varchar(16) NOT NULL CHECK (severity IN ('p0', 'p1', 'p2', 'p3')),
            source varchar(64) NOT NULL,
            run_id uuid NULL REFERENCES runtime.agent_runs(run_id),
            eval_run_id uuid NULL,
            case_id varchar(128) NULL,
            trace_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
            status varchar(32) NOT NULL DEFAULT 'open',
            cluster_key varchar(160) NOT NULL,
            summary_redacted text NOT NULL CHECK (length(summary_redacted) <= 2000),
            source_count integer NOT NULL DEFAULT 1 CHECK (source_count >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NULL
        );
        CREATE INDEX IF NOT EXISTS ix_failure_cases_tenant_status
          ON evaluation.failure_cases (tenant_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_failure_cases_cluster
          ON evaluation.failure_cases (tenant_id, cluster_key, created_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_failure_case_run_cluster
          ON evaluation.failure_cases (tenant_id, run_id, cluster_key)
          WHERE run_id IS NOT NULL;

        CREATE TABLE IF NOT EXISTS evaluation.failure_attributions (
            attribution_id uuid PRIMARY KEY,
            failure_id uuid NOT NULL REFERENCES evaluation.failure_cases(failure_id),
            deterministic_category varchar(64) NOT NULL,
            llm_category varchar(64) NULL,
            confidence numeric(6,5) NULL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
            model_hash varchar(80) NULL,
            prompt_hash varchar(80) NULL,
            review_status varchar(32) NOT NULL DEFAULT 'pending',
            rationale_redacted text NULL CHECK (rationale_redacted IS NULL OR length(rationale_redacted) <= 2000),
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_failure_attributions_failure
          ON evaluation.failure_attributions (failure_id, created_at DESC);
        GRANT USAGE ON SCHEMA feedback TO commerce_agent_runtime;
        GRANT SELECT, INSERT, UPDATE ON feedback.user_feedback TO commerce_agent_runtime;
        GRANT SELECT, INSERT, UPDATE ON evaluation.failure_cases, evaluation.failure_attributions
          TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    # Retain user feedback and attribution evidence on downgrade.  Only safe
    # lookup indexes are removable without an explicit retention decision.
    op.execute("DROP INDEX IF EXISTS evaluation.ix_failure_attributions_failure")
    op.execute("DROP INDEX IF EXISTS evaluation.uq_failure_case_run_cluster")
    op.execute("DROP INDEX IF EXISTS evaluation.ix_failure_cases_cluster")
    op.execute("DROP INDEX IF EXISTS evaluation.ix_failure_cases_tenant_status")
    op.execute("DROP INDEX IF EXISTS feedback.ix_user_feedback_run_created")
