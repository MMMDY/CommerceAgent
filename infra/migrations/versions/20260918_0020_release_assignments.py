"""Persist safe, tenant-scoped release traffic assignments."""

from alembic import op

revision = "20260918_0020"
down_revision = "20260917_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS release.release_assignments (
            assignment_id uuid PRIMARY KEY,
            release_id uuid NOT NULL REFERENCES release.releases(release_id),
            tenant_id varchar(64) NOT NULL,
            run_id uuid NOT NULL REFERENCES runtime.agent_runs(run_id),
            actor_key_hash varchar(80) NOT NULL,
            conversation_key_hash varchar(80) NOT NULL,
            current_version varchar(128) NOT NULL,
            candidate_version varchar(128) NOT NULL,
            selected_version varchar(128) NOT NULL,
            mode varchar(16) NOT NULL CHECK (mode IN ('current', 'shadow', 'canary')),
            bucket integer NOT NULL CHECK (bucket >= 0 AND bucket <= 99),
            traffic_percent integer NOT NULL CHECK (traffic_percent >= 0 AND traffic_percent <= 100),
            risk_level varchar(16) NOT NULL,
            risk_hint varchar(16) NOT NULL,
            reason varchar(128) NOT NULL,
            comparison_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (release_id, run_id)
        );
        CREATE INDEX IF NOT EXISTS ix_release_assignments_tenant_created
          ON release.release_assignments (tenant_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_release_assignments_release_mode
          ON release.release_assignments (release_id, mode, created_at DESC);
        GRANT SELECT, INSERT ON release.release_assignments TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS release.ix_release_assignments_release_mode")
    op.execute("DROP INDEX IF EXISTS release.ix_release_assignments_tenant_created")
    op.execute("DROP TABLE IF EXISTS release.release_assignments")
