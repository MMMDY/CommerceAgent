"""Add Phase 3 knowledge uniqueness and text-search indexes.

Revision ID: 20260914_0007
Revises: 20260914_0006
"""

from alembic import op

revision = "20260914_0007"
down_revision = "20260914_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_document_source_version "
        "ON knowledge.knowledge_documents (tenant_id, source_uri, version)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_trgm "
        "ON knowledge.knowledge_chunks USING gin (text_redacted gin_trgm_ops)"
    )
    op.execute("GRANT USAGE ON SCHEMA knowledge TO commerce_agent_runtime")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON knowledge.knowledge_documents, knowledge.knowledge_chunks "
        "TO commerce_agent_runtime"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS knowledge.ix_knowledge_chunks_trgm")
    op.execute("DROP INDEX IF EXISTS knowledge.uq_knowledge_document_source_version")
