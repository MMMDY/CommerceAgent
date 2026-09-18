"""Register executable release runtimes before candidate traffic is enabled."""

from alembic import op

revision = "20260918_0021"
down_revision = "20260918_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS release.runtime_registrations (
            registration_id uuid PRIMARY KEY,
            tenant_id varchar(64) NOT NULL,
            version varchar(128) NOT NULL,
            runtime_hash varchar(128) NOT NULL,
            status varchar(16) NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED')),
            metadata_redacted_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            retired_at timestamptz NULL,
            UNIQUE (tenant_id, version)
        );
        CREATE INDEX IF NOT EXISTS ix_runtime_registrations_lookup
          ON release.runtime_registrations (tenant_id, version, status);
        GRANT SELECT, INSERT, UPDATE ON release.runtime_registrations
          TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS release.ix_runtime_registrations_lookup")
    op.execute("DROP TABLE IF EXISTS release.runtime_registrations")
