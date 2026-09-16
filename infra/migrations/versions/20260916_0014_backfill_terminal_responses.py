"""Backfill terminal projection markers for existing assistant messages.

Revision ID: 20260916_0014
Revises: 20260916_0013
"""

from alembic import op

revision = "20260916_0014"
down_revision = "20260916_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve the earliest assistant response already shown to the user. The
    # unique index from 0013 then prevents a second terminal projection.
    op.execute(
        """
        WITH first_response AS (
            SELECT DISTINCT ON (message.run_id) message.message_id
            FROM conversation.messages AS message
            JOIN runtime.agent_runs AS run ON run.run_id = message.run_id
            WHERE message.role = 'assistant'
              AND run.status IN ('completed', 'failed', 'cancelled', 'expired')
              AND NOT EXISTS (
                  SELECT 1 FROM conversation.messages AS existing
                  WHERE existing.run_id = message.run_id
                    AND existing.is_terminal IS TRUE
              )
            ORDER BY message.run_id, message.sequence_no ASC
        )
        UPDATE conversation.messages AS message
        SET is_terminal = TRUE
        FROM first_response
        WHERE message.message_id = first_response.message_id
        """
    )


def downgrade() -> None:
    # The marker is derived compatibility metadata; removing it is safe and
    # leaves all message content intact.
    op.execute(
        """
        UPDATE conversation.messages AS message
        SET is_terminal = FALSE
        FROM runtime.agent_runs AS run
        WHERE run.run_id = message.run_id
          AND run.status IN ('completed', 'failed', 'cancelled', 'expired')
        """
    )
