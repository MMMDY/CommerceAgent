"""Create confirmation, idempotency, and outbox persistence.

Revision ID: 20260913_0003
Revises: 20260913_0002
"""

from alembic import op

revision = "20260913_0003"
down_revision = "20260913_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE runtime.confirmation_tokens (
            token_id uuid PRIMARY KEY,
            token_hash varchar(128) NOT NULL UNIQUE,
            run_id uuid NOT NULL REFERENCES runtime.agent_runs(run_id),
            tenant_id varchar(64) NOT NULL,
            actor_ref varchar(128) NOT NULL,
            mutation_type varchar(64) NOT NULL,
            resource_ref varchar(128) NOT NULL,
            preview_hash varchar(80) NOT NULL,
            arguments_hash varchar(80) NOT NULL,
            policy_version varchar(64) NOT NULL,
            workflow_version varchar(32) NOT NULL,
            status varchar(24) NOT NULL,
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz NULL,
            confirmation_message_id uuid NULL,
            created_at timestamptz NOT NULL,
            row_version bigint NOT NULL DEFAULT 0
        );
        CREATE INDEX ix_confirmation_tokens_run_status
          ON runtime.confirmation_tokens (run_id, status, expires_at);
        CREATE TABLE runtime.idempotency_records (
            idempotency_record_id uuid PRIMARY KEY,
            tenant_id varchar(64) NOT NULL,
            operation varchar(80) NOT NULL,
            idempotency_key_hash varchar(128) NOT NULL,
            request_fingerprint varchar(80) NOT NULL,
            status varchar(24) NOT NULL,
            business_reference varchar(128) NULL,
            response_redacted_json jsonb NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            expires_at timestamptz NULL,
            row_version bigint NOT NULL DEFAULT 0,
            UNIQUE (tenant_id, operation, idempotency_key_hash)
        );
        CREATE TABLE runtime.runtime_outbox (
            outbox_id uuid PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES runtime.agent_runs(run_id),
            event_id uuid NOT NULL REFERENCES runtime.run_events(event_id),
            topic varchar(128) NOT NULL,
            payload_redacted_json jsonb NOT NULL,
            status varchar(16) NOT NULL DEFAULT 'pending',
            attempt_count integer NOT NULL DEFAULT 0,
            available_at timestamptz NOT NULL,
            locked_at timestamptz NULL,
            published_at timestamptz NULL,
            last_error varchar(500) NULL,
            created_at timestamptz NOT NULL,
            UNIQUE (event_id, topic)
        );
        CREATE INDEX ix_runtime_outbox_lease
          ON runtime.runtime_outbox (status, available_at);
        GRANT SELECT, INSERT, UPDATE ON runtime.confirmation_tokens,
          runtime.idempotency_records, runtime.runtime_outbox TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS runtime.runtime_outbox")
    op.execute("DROP TABLE IF EXISTS runtime.idempotency_records")
    op.execute("DROP TABLE IF EXISTS runtime.confirmation_tokens")
