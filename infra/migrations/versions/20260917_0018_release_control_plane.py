"""Persist Shadow/Canary release stages, gates and stop audit events."""

from alembic import op

revision = "20260917_0018"
down_revision = "20260917_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS release;
        CREATE TABLE IF NOT EXISTS release.releases (
            release_id uuid PRIMARY KEY,
            tenant_id varchar(64) NOT NULL,
            owner_ref varchar(128) NOT NULL,
            current_version varchar(128) NOT NULL,
            candidate_version varchar(128) NOT NULL,
            stage varchar(24) NOT NULL CHECK (stage IN ('SHADOW', 'CANARY_5', 'CANARY_25', 'CANARY_50', 'FULL', 'STOPPED', 'ROLLED_BACK')),
            status varchar(24) NOT NULL CHECK (status IN ('ACTIVE', 'PAUSED', 'STOPPED', 'COMPLETED', 'ROLLED_BACK')),
            traffic_percent integer NOT NULL CHECK (traffic_percent >= 0 AND traffic_percent <= 100),
            observation_started_at timestamptz NULL,
            observation_ends_at timestamptz NULL,
            baseline_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            candidate_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            gates_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            stop_reason varchar(128) NULL,
            rollback_version varchar(128) NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_releases_tenant_updated
          ON release.releases (tenant_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS release.release_events (
            event_id uuid PRIMARY KEY,
            release_id uuid NOT NULL REFERENCES release.releases(release_id),
            event_type varchar(64) NOT NULL,
            actor_ref varchar(128) NULL,
            payload_redacted_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_release_events_release
          ON release.release_events (release_id, created_at DESC);
        GRANT USAGE ON SCHEMA release TO commerce_agent_runtime;
        GRANT SELECT, INSERT, UPDATE ON release.releases, release.release_events
          TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS release.ix_release_events_release")
    op.execute("DROP INDEX IF EXISTS release.ix_releases_tenant_updated")
