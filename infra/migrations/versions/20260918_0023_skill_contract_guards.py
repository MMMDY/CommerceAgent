"""Add database-side guards for generated Skill contracts and global scope."""

from alembic import op

revision = "20260918_0023"
down_revision = "20260918_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE experience.skill_candidates
          ADD COLUMN IF NOT EXISTS owner varchar(64) NOT NULL DEFAULT 'tenant',
          ADD COLUMN IF NOT EXISTS kind varchar(32) NOT NULL DEFAULT 'experience';

        ALTER TABLE experience.skill_versions
          ADD COLUMN IF NOT EXISTS contract_version smallint;

        -- Skill versions are immutable by design.  Grandfather only rows that
        -- predate this contract; every new row receives version 2 below and is
        -- required to satisfy the complete generated-Skill shape.
        UPDATE experience.skill_versions
        SET contract_version = CASE
          WHEN jsonb_typeof(definition_json) = 'object'
           AND definition_json ? 'trigger'
           AND definition_json ? 'response_policy'
           AND definition_json ? 'scope'
           AND definition_json ? 'positive_examples'
           AND definition_json ? 'negative_examples'
           AND definition_json ? 'forbidden_tools'
           AND definition_json ? 'ttl_seconds'
          THEN 2
          ELSE 1
        END
        WHERE contract_version IS NULL;
        ALTER TABLE experience.skill_versions
          ALTER COLUMN contract_version SET DEFAULT 2,
          ALTER COLUMN contract_version SET NOT NULL;

        -- Older candidates and versions were created before the generated-Skill
        -- contract existed.  Normalize only missing structural fields so the
        -- constraint can be introduced without discarding existing evidence or
        -- changing an already populated value.
        UPDATE experience.skill_candidates
        SET trigger_json = CASE
              WHEN jsonb_typeof(trigger_json) = 'object'
                THEN jsonb_build_object('keywords', '[]'::jsonb) || trigger_json
              ELSE '{"keywords": []}'::jsonb
            END,
            strategy_json = CASE
              WHEN jsonb_typeof(strategy_json) = 'object'
                THEN jsonb_build_object('response_policy', 'conversational_response') || strategy_json
              ELSE '{"response_policy": "conversational_response"}'::jsonb
            END,
            provenance_json = CASE
              WHEN jsonb_typeof(provenance_json) = 'object' THEN provenance_json
              ELSE '{}'::jsonb
            END
        WHERE jsonb_typeof(trigger_json) <> 'object'
           OR NOT (trigger_json ? 'keywords')
           OR jsonb_typeof(strategy_json) <> 'object'
           OR NOT (strategy_json ? 'response_policy')
           OR jsonb_typeof(provenance_json) <> 'object';

        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'skill_candidates_json_contract'
          ) THEN
            ALTER TABLE experience.skill_candidates
              ADD CONSTRAINT skill_candidates_json_contract CHECK (
                jsonb_typeof(trigger_json) = 'object'
                AND trigger_json ? 'keywords'
                AND jsonb_typeof(strategy_json) = 'object'
                AND strategy_json ? 'response_policy'
                AND jsonb_typeof(provenance_json) = 'object'
              );
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'skill_candidates_global_scope_guard'
          ) THEN
            ALTER TABLE experience.skill_candidates
              ADD CONSTRAINT skill_candidates_global_scope_guard CHECK (
                scope_type <> 'global'
                OR (owner = 'project' AND kind = 'safety')
              );
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'skill_versions_json_contract'
          ) THEN
            ALTER TABLE experience.skill_versions
              ADD CONSTRAINT skill_versions_json_contract CHECK (
                contract_version = 1
                OR (
                  contract_version = 2
                  AND jsonb_typeof(definition_json) = 'object'
                  AND definition_json ? 'trigger'
                  AND definition_json ? 'response_policy'
                  AND definition_json ? 'scope'
                  AND definition_json ? 'positive_examples'
                  AND definition_json ? 'negative_examples'
                  AND definition_json ? 'forbidden_tools'
                  AND definition_json ? 'ttl_seconds'
                )
              );
          END IF;
        END $$;
        CREATE INDEX IF NOT EXISTS ix_skill_candidates_owner_kind
          ON experience.skill_candidates (tenant_id, owner, kind, status);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS experience.ix_skill_candidates_owner_kind;
        ALTER TABLE experience.skill_versions
          DROP CONSTRAINT IF EXISTS skill_versions_json_contract;
        ALTER TABLE experience.skill_candidates
          DROP CONSTRAINT IF EXISTS skill_candidates_global_scope_guard,
          DROP CONSTRAINT IF EXISTS skill_candidates_json_contract;
        ALTER TABLE experience.skill_versions
          DROP COLUMN IF EXISTS contract_version;
        ALTER TABLE experience.skill_candidates
          DROP COLUMN IF EXISTS owner,
          DROP COLUMN IF EXISTS kind;
        """
    )
