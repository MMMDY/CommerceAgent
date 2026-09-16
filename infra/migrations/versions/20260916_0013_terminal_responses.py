"""Mark terminal assistant projections and enforce one per Run.

Revision ID: 20260916_0013
Revises: 20260916_0012
"""

from alembic import op

revision = "20260916_0013"
down_revision = "20260916_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversation.messages ADD COLUMN IF NOT EXISTS is_terminal boolean NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_one_terminal_response "
        "ON conversation.messages (run_id) WHERE run_id IS NOT NULL AND is_terminal IS TRUE"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON conversation.messages TO commerce_agent_runtime")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS conversation.uq_messages_one_terminal_response")
    op.execute("ALTER TABLE conversation.messages DROP COLUMN IF EXISTS is_terminal")
