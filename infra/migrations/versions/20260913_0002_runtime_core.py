"""Create Phase 1 conversation and runtime core tables.

Revision ID: 20260913_0002
Revises: 20260913_0001
"""

from alembic import op

revision = "20260913_0002"
down_revision = "20260913_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversation.messages (
            message_id uuid PRIMARY KEY,
            conversation_id uuid NOT NULL REFERENCES conversation.conversations(id),
            run_id uuid NULL,
            role varchar(16) NOT NULL,
            content_redacted text NOT NULL,
            content_hash varchar(80) NOT NULL,
            pii_labels_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            sequence_no bigint NOT NULL,
            created_at timestamptz NOT NULL,
            UNIQUE (conversation_id, sequence_no)
        );
        CREATE INDEX ix_messages_run_created ON conversation.messages (run_id, created_at);
        CREATE TABLE runtime.agent_runs (
            run_id uuid PRIMARY KEY,
            conversation_id uuid NOT NULL REFERENCES conversation.conversations(id),
            parent_run_id uuid NULL,
            tenant_id varchar(64) NOT NULL,
            actor_ref varchar(128) NOT NULL,
            status varchar(32) NOT NULL,
            execution_mode varchar(24) NOT NULL,
            workflow_id varchar(64) NOT NULL,
            workflow_version varchar(32) NOT NULL,
            policy_version varchar(64) NOT NULL,
            model_config_hash varchar(80) NOT NULL,
            prompt_version varchar(64) NOT NULL,
            current_step varchar(64) NOT NULL,
            step_count integer NOT NULL CHECK (step_count >= 0),
            max_steps integer NOT NULL CHECK (max_steps BETWEEN 1 AND 6),
            deadline_at timestamptz NOT NULL,
            cancel_requested_at timestamptz NULL,
            terminal_reason varchar(128) NULL,
            last_checkpoint_seq bigint NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            row_version bigint NOT NULL DEFAULT 0
        );
        CREATE UNIQUE INDEX uq_agent_runs_active_conversation
          ON runtime.agent_runs (conversation_id)
          WHERE status NOT IN ('completed', 'failed', 'cancelled', 'expired');
        CREATE INDEX ix_agent_runs_tenant_status_updated
          ON runtime.agent_runs (tenant_id, status, updated_at DESC);
        CREATE TABLE runtime.run_checkpoints (
            run_id uuid NOT NULL REFERENCES runtime.agent_runs(run_id),
            checkpoint_seq bigint NOT NULL CHECK (checkpoint_seq > 0),
            schema_version varchar(32) NOT NULL,
            step_id varchar(64) NOT NULL,
            state_json jsonb NOT NULL,
            state_hash varchar(80) NOT NULL,
            event_from_seq bigint NOT NULL,
            event_to_seq bigint NOT NULL,
            created_at timestamptz NOT NULL,
            PRIMARY KEY (run_id, checkpoint_seq)
        );
        CREATE TABLE runtime.run_events (
            event_id uuid PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES runtime.agent_runs(run_id),
            event_seq bigint NOT NULL CHECK (event_seq > 0),
            event_type varchar(64) NOT NULL,
            event_version varchar(16) NOT NULL,
            step_id varchar(64) NOT NULL,
            payload_json jsonb NOT NULL,
            payload_hash varchar(80) NOT NULL,
            causation_id uuid NULL,
            correlation_id uuid NOT NULL,
            created_at timestamptz NOT NULL,
            UNIQUE (run_id, event_seq)
        );
        GRANT SELECT, INSERT, UPDATE ON conversation.messages TO commerce_agent_runtime;
        GRANT USAGE ON SCHEMA runtime TO commerce_agent_runtime;
        GRANT SELECT, INSERT, UPDATE ON runtime.agent_runs, runtime.run_checkpoints,
          runtime.run_events TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS runtime.run_events")
    op.execute("DROP TABLE IF EXISTS runtime.run_checkpoints")
    op.execute("DROP TABLE IF EXISTS runtime.agent_runs")
    op.execute("DROP TABLE IF EXISTS conversation.messages")
