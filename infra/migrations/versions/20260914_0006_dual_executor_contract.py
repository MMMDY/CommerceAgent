"""Allow pre-route runs and enforce immutable dual-executor selection.

Revision ID: 20260914_0006
Revises: 20260913_0005
"""

from alembic import op

revision = "20260914_0006"
down_revision = "20260913_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE runtime.agent_runs ALTER COLUMN execution_mode DROP NOT NULL;
        ALTER TABLE runtime.agent_runs ALTER COLUMN workflow_id DROP NOT NULL;
        ALTER TABLE runtime.agent_runs ALTER COLUMN workflow_version DROP NOT NULL;

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

        ALTER TABLE runtime.agent_runs
          ADD CONSTRAINT ck_agent_runs_mode_matches_status CHECK (
            status <> 'running_readonly' OR execution_mode = 'readonly_loop'
          );
        ALTER TABLE runtime.agent_runs
          ADD CONSTRAINT ck_agent_runs_workflow_states CHECK (
            status NOT IN ('running_workflow', 'waiting_confirmation', 'committing', 'verifying')
            OR execution_mode = 'workflow'
          );

        CREATE FUNCTION runtime.guard_agent_run_executor_selection() RETURNS trigger AS $$
        BEGIN
          IF OLD.execution_mode IS NOT NULL AND NEW.execution_mode IS DISTINCT FROM OLD.execution_mode THEN
            RAISE EXCEPTION 'agent run execution mode is immutable once selected';
          END IF;
          IF OLD.workflow_id IS NOT NULL AND (
             NEW.workflow_id IS DISTINCT FROM OLD.workflow_id
             OR NEW.workflow_version IS DISTINCT FROM OLD.workflow_version
          ) THEN
            RAISE EXCEPTION 'agent run workflow version is immutable once selected';
          END IF;
          IF OLD.execution_mode IS NULL AND NEW.execution_mode IS NOT NULL
             AND OLD.status NOT IN ('created', 'routing') THEN
            RAISE EXCEPTION 'agent run executor can only be selected while routing';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER agent_runs_executor_selection_immutable
          BEFORE UPDATE ON runtime.agent_runs
          FOR EACH ROW EXECUTE FUNCTION runtime.guard_agent_run_executor_selection();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS agent_runs_executor_selection_immutable ON runtime.agent_runs;
        DROP FUNCTION IF EXISTS runtime.guard_agent_run_executor_selection();
        ALTER TABLE runtime.agent_runs DROP CONSTRAINT IF EXISTS ck_agent_runs_workflow_states;
        ALTER TABLE runtime.agent_runs DROP CONSTRAINT IF EXISTS ck_agent_runs_mode_matches_status;
        ALTER TABLE runtime.agent_runs DROP CONSTRAINT IF EXISTS ck_agent_runs_dual_executor_shape;
        ALTER TABLE runtime.agent_runs ALTER COLUMN execution_mode SET NOT NULL;
        ALTER TABLE runtime.agent_runs ALTER COLUMN workflow_id SET NOT NULL;
        ALTER TABLE runtime.agent_runs ALTER COLUMN workflow_version SET NOT NULL;
        """
    )
