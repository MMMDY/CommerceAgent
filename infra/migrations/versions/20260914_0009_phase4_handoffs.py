"""Persist Phase 4 uncertain mutation handoffs.

Revision ID: 20260914_0009
Revises: 20260914_0008
"""

from alembic import op

revision = "20260914_0009"
down_revision = "20260914_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE runtime.handoff_tickets (
            ticket_id uuid PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES runtime.agent_runs(run_id),
            tenant_id varchar(64) NOT NULL,
            actor_ref varchar(128) NOT NULL,
            reason_code varchar(64) NOT NULL,
            status varchar(24) NOT NULL,
            operation varchar(80) NULL,
            details_redacted_json jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            resolved_at timestamptz NULL,
            resolution varchar(500) NULL
        );
        CREATE INDEX ix_handoff_tickets_run_status
          ON runtime.handoff_tickets (run_id, tenant_id, status);
        GRANT SELECT, INSERT, UPDATE ON runtime.handoff_tickets TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS runtime.handoff_tickets")
