"""Add explicit outbox dead-letter metadata for Phase 6 operations."""

from alembic import op

revision = "20260916_0011"
down_revision = "20260915_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE runtime.runtime_outbox
          ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz NULL;
        CREATE INDEX IF NOT EXISTS ix_runtime_outbox_dead_letter
          ON runtime.runtime_outbox (status, attempt_count, available_at);
        """
    )


def downgrade() -> None:
    # Retain the column during downgrade to avoid deleting operational data.
    op.execute("DROP INDEX IF EXISTS runtime.ix_runtime_outbox_dead_letter")
