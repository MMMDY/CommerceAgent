"""Preserve merged failure signals and make correction retention maintainable."""

from alembic import op

revision = "20260918_0022"
down_revision = "20260918_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE evaluation.failure_cases
          ADD COLUMN IF NOT EXISTS signals_json jsonb NOT NULL DEFAULT '[]'::jsonb;

        ALTER TABLE feedback.user_feedback
          ADD COLUMN IF NOT EXISTS correction_hash varchar(80) NULL;

        UPDATE evaluation.failure_cases
        SET signals_json = jsonb_build_array(
          jsonb_build_object(
            'signal', signal,
            'severity', severity,
            'source', source
          )
        )
        WHERE signals_json = '[]'::jsonb;

        CREATE INDEX IF NOT EXISTS ix_failure_cases_signal_gin
          ON evaluation.failure_cases USING gin (signals_json);

        CREATE INDEX IF NOT EXISTS ix_user_feedback_expiry
          ON feedback.user_feedback (expires_at)
          WHERE correction_redacted IS NOT NULL;

        REVOKE DELETE ON feedback.user_feedback,
          evaluation.failure_cases, evaluation.failure_attributions
          FROM commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    # Retain merged signal and feedback evidence during downgrade.  Removing
    # the projection would lose audit context; only the lookup indexes are
    # safely reversible.
    op.execute("DROP INDEX IF EXISTS feedback.ix_user_feedback_expiry")
    op.execute("DROP INDEX IF EXISTS evaluation.ix_failure_cases_signal_gin")
