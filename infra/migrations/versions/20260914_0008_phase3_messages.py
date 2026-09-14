"""Add client message idempotency for Phase 3 conversation APIs.

Revision ID: 20260914_0008
Revises: 20260914_0007
"""

from alembic import op

revision = "20260914_0008"
down_revision = "20260914_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversation.messages ADD COLUMN IF NOT EXISTS client_message_id varchar(128)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_client_id "
        "ON conversation.messages (conversation_id, client_message_id) "
        "WHERE client_message_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_conversation_sequence "
        "ON conversation.messages (conversation_id, sequence_no)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON conversation.messages TO commerce_agent_runtime")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS conversation.ix_messages_conversation_sequence")
    op.execute("DROP INDEX IF EXISTS conversation.uq_messages_client_id")
    op.execute("ALTER TABLE conversation.messages DROP COLUMN IF EXISTS client_message_id")
