"""Allow runtime to enrich an existing release assignment comparison."""

from alembic import op

revision = "20260918_0025"
down_revision = "20260918_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        GRANT UPDATE (comparison_json) ON release.release_assignments
          TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE UPDATE (comparison_json) ON release.release_assignments
          FROM commerce_agent_runtime;
        """
    )
