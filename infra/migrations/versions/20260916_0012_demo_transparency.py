"""Allow pre-execution runs to be expired during restart recovery.

Revision ID: 20260916_0012
Revises: 20260916_0011
"""

from alembic import op

revision = "20260916_0012"
down_revision = "20260916_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE runtime.agent_runs
          DROP CONSTRAINT IF EXISTS ck_agent_runs_dual_executor_shape;
        ALTER TABLE runtime.agent_runs
          ADD CONSTRAINT ck_agent_runs_dual_executor_shape CHECK (
            (execution_mode IS NULL AND workflow_id IS NULL AND workflow_version IS NULL
              AND status IN ('created', 'routing', 'waiting_human', 'failed', 'cancelled', 'expired'))
            OR
            (execution_mode = 'readonly_loop' AND workflow_id IS NOT NULL
              AND workflow_version IS NOT NULL)
            OR
            (execution_mode = 'workflow' AND workflow_id IS NOT NULL
              AND workflow_version IS NOT NULL)
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE runtime.agent_runs
          DROP CONSTRAINT IF EXISTS ck_agent_runs_dual_executor_shape;
        ALTER TABLE runtime.agent_runs
          ADD CONSTRAINT ck_agent_runs_dual_executor_shape CHECK (
            (execution_mode IS NULL AND workflow_id IS NULL AND workflow_version IS NULL
              AND status IN ('created', 'routing', 'waiting_human'))
            OR
            (execution_mode = 'readonly_loop' AND workflow_id IS NOT NULL
              AND workflow_version IS NOT NULL)
            OR
            (execution_mode = 'workflow' AND workflow_id IS NOT NULL
              AND workflow_version IS NOT NULL)
          );
        """
    )
