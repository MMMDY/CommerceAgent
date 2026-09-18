"""Add a tenant-scoped, fail-closed Skill matching kill switch."""

from alembic import op

revision = "20260918_0024"
down_revision = "20260918_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS experience.skill_controls (
            tenant_id varchar(64) PRIMARY KEY,
            matching_enabled boolean NOT NULL DEFAULT true,
            updated_by varchar(128) NOT NULL,
            reason_hash varchar(80) NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_skill_controls_updated
          ON experience.skill_controls (updated_at DESC);
        GRANT SELECT ON experience.skill_controls TO commerce_agent_runtime;
        GRANT INSERT, UPDATE ON experience.skill_controls TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS experience.ix_skill_controls_updated")
    op.execute("DROP TABLE IF EXISTS experience.skill_controls")
