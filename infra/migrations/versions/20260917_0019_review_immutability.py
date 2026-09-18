"""Add human attribution review fields and immutable Skill version guards."""

from alembic import op

revision = "20260917_0019"
down_revision = "20260917_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE evaluation.failure_attributions
          ADD COLUMN IF NOT EXISTS reviewed_category varchar(64) NULL,
          ADD COLUMN IF NOT EXISTS reviewed_by varchar(128) NULL,
          ADD COLUMN IF NOT EXISTS reviewed_at timestamptz NULL,
          ADD COLUMN IF NOT EXISTS review_note_redacted text NULL
            CHECK (review_note_redacted IS NULL OR length(review_note_redacted) <= 2000);

        CREATE FUNCTION experience.reject_skill_version_definition_update() RETURNS trigger AS $$
        BEGIN
          IF NEW.skill_id IS DISTINCT FROM OLD.skill_id
             OR NEW.version_no IS DISTINCT FROM OLD.version_no
             OR NEW.definition_json IS DISTINCT FROM OLD.definition_json
             OR NEW.definition_hash IS DISTINCT FROM OLD.definition_hash THEN
            RAISE EXCEPTION 'skill version definition is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER skill_versions_immutable_definition
          BEFORE UPDATE ON experience.skill_versions
          FOR EACH ROW EXECUTE FUNCTION experience.reject_skill_version_definition_update();
        GRANT SELECT, INSERT, UPDATE ON evaluation.failure_attributions TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS skill_versions_immutable_definition ON experience.skill_versions;
        DROP FUNCTION IF EXISTS experience.reject_skill_version_definition_update();
        """
    )
    # Review columns are intentionally retained on downgrade so a rollback
    # cannot erase human decisions that are already part of the audit trail.
