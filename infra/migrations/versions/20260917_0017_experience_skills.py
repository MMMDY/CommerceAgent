"""Persist generated experience candidates and immutable Skill versions."""

from alembic import op

revision = "20260917_0017"
down_revision = "20260917_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS experience;
        CREATE TABLE IF NOT EXISTS experience.skill_candidates (
            skill_id uuid PRIMARY KEY,
            tenant_id varchar(64) NOT NULL,
            scope_type varchar(24) NOT NULL CHECK (scope_type IN ('tenant', 'route', 'global')),
            scope_value varchar(128) NOT NULL,
            trigger_json jsonb NOT NULL,
            strategy_json jsonb NOT NULL,
            provenance_json jsonb NOT NULL,
            cluster_key varchar(160) NOT NULL,
            status varchar(32) NOT NULL CHECK (status IN ('CANDIDATE', 'PENDING_REVIEW', 'APPROVED', 'CANARY', 'ACTIVE', 'REJECTED', 'EXPIRED', 'ROLLED_BACK')),
            source_count integer NOT NULL DEFAULT 0 CHECK (source_count >= 0),
            positive_count integer NOT NULL DEFAULT 0 CHECK (positive_count >= 0),
            negative_count integer NOT NULL DEFAULT 0 CHECK (negative_count >= 0),
            offline_gate_pass boolean NOT NULL DEFAULT false,
            safety_gate_pass boolean NOT NULL DEFAULT false,
            review_deadline timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_skill_candidates_tenant_status
          ON experience.skill_candidates (tenant_id, status, updated_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_candidates_active_scope
          ON experience.skill_candidates (tenant_id, scope_type, scope_value)
          WHERE status IN ('CANARY', 'ACTIVE');

        CREATE TABLE IF NOT EXISTS experience.skill_versions (
            skill_version_id uuid PRIMARY KEY,
            skill_id uuid NOT NULL REFERENCES experience.skill_candidates(skill_id),
            version_no integer NOT NULL CHECK (version_no >= 1),
            definition_json jsonb NOT NULL,
            definition_hash varchar(80) NOT NULL UNIQUE,
            approved_by varchar(128) NULL,
            approved_at timestamptz NULL,
            activated_at timestamptz NULL,
            expires_at timestamptz NOT NULL,
            rollback_of uuid NULL REFERENCES experience.skill_versions(skill_version_id),
            status varchar(32) NOT NULL CHECK (status IN ('PENDING_REVIEW', 'APPROVED', 'CANARY', 'ACTIVE', 'EXPIRED', 'ROLLED_BACK')),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (skill_id, version_no)
        );
        CREATE INDEX IF NOT EXISTS ix_skill_versions_expiry
          ON experience.skill_versions (status, expires_at);

        CREATE TABLE IF NOT EXISTS experience.skill_matches (
            match_id uuid PRIMARY KEY,
            tenant_id varchar(64) NOT NULL,
            run_id uuid NOT NULL REFERENCES runtime.agent_runs(run_id),
            skill_id uuid NOT NULL REFERENCES experience.skill_candidates(skill_id),
            skill_version_id uuid NOT NULL REFERENCES experience.skill_versions(skill_version_id),
            match_score numeric(6,5) NOT NULL CHECK (match_score >= 0 AND match_score <= 1),
            mode varchar(16) NOT NULL CHECK (mode IN ('shadow', 'canary', 'active')),
            outcome varchar(32) NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_skill_matches_run
          ON experience.skill_matches (tenant_id, run_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS experience.skill_evaluations (
            evaluation_id uuid PRIMARY KEY,
            skill_id uuid NOT NULL REFERENCES experience.skill_candidates(skill_id),
            skill_version_id uuid NULL REFERENCES experience.skill_versions(skill_version_id),
            dataset_hash varchar(80) NOT NULL,
            before_json jsonb NOT NULL,
            after_json jsonb NOT NULL,
            safety_result varchar(32) NOT NULL,
            cost_delta_microusd bigint NULL,
            latency_delta_ms bigint NULL,
            gate_pass boolean NOT NULL,
            judge_disagreement_count integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_skill_evaluations_skill
          ON experience.skill_evaluations (skill_id, created_at DESC);
        GRANT USAGE ON SCHEMA experience TO commerce_agent_runtime;
        GRANT SELECT, INSERT, UPDATE ON experience.skill_candidates, experience.skill_versions,
          experience.skill_matches, experience.skill_evaluations TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS experience.ix_skill_evaluations_skill")
    op.execute("DROP INDEX IF EXISTS experience.ix_skill_matches_run")
    op.execute("DROP INDEX IF EXISTS experience.ix_skill_versions_expiry")
    op.execute("DROP INDEX IF EXISTS experience.uq_skill_candidates_active_scope")
    op.execute("DROP INDEX IF EXISTS experience.ix_skill_candidates_tenant_status")
