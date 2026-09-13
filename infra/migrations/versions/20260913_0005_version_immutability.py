"""Prevent mutation of active workflow and policy definitions.

Revision ID: 20260913_0005
Revises: 20260913_0004
"""

from alembic import op

revision = "20260913_0005"
down_revision = "20260913_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION domain.reject_active_definition_update() RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'active' AND (NEW.definition_json IS DISTINCT FROM OLD.definition_json
             OR NEW.definition_hash IS DISTINCT FROM OLD.definition_hash) THEN
            RAISE EXCEPTION 'active workflow version is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER workflow_versions_immutable_active
          BEFORE UPDATE ON domain.workflow_versions
          FOR EACH ROW EXECUTE FUNCTION domain.reject_active_definition_update();
        CREATE FUNCTION domain.reject_active_rules_update() RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'active' AND (NEW.rules_json IS DISTINCT FROM OLD.rules_json
             OR NEW.rules_hash IS DISTINCT FROM OLD.rules_hash) THEN
            RAISE EXCEPTION 'active policy version is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER policy_versions_immutable_active
          BEFORE UPDATE ON domain.policy_versions
          FOR EACH ROW EXECUTE FUNCTION domain.reject_active_rules_update();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS workflow_versions_immutable_active ON domain.workflow_versions")
    op.execute("DROP TRIGGER IF EXISTS policy_versions_immutable_active ON domain.policy_versions")
    op.execute("DROP FUNCTION IF EXISTS domain.reject_active_definition_update()")
    op.execute("DROP FUNCTION IF EXISTS domain.reject_active_rules_update()")
