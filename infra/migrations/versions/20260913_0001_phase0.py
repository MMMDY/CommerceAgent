"""Create Phase 0 schemas and minimal conversation persistence.

Revision ID: 20260913_0001
Revises:
Create Date: 2026-09-13
"""

from alembic import op

revision = "20260913_0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ("conversation", "runtime", "domain", "memory", "knowledge", "evaluation", "audit")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE TABLE conversation.conversations (
            id uuid PRIMARY KEY,
            tenant_id varchar(64) NOT NULL,
            actor_id varchar(128) NOT NULL,
            client_request_id varchar(128) NOT NULL,
            status varchar(32) NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT uq_conversation_actor_request
                UNIQUE (tenant_id, actor_id, client_request_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_conversations_tenant_actor_updated "
        "ON conversation.conversations (tenant_id, actor_id, updated_at DESC)"
    )
    op.execute("GRANT USAGE ON SCHEMA conversation TO commerce_agent_runtime")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON conversation.conversations TO commerce_agent_runtime"
    )
    op.execute("GRANT SELECT ON TABLE public.alembic_version TO commerce_agent_runtime")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation.conversations")
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}"')
