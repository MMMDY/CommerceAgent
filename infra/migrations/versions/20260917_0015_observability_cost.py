"""Add auditable token, timing, and model cost metadata."""

from alembic import op

revision = "20260917_0015"
down_revision = "20260916_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS domain.model_pricing_versions (
            pricing_version_id uuid PRIMARY KEY,
            provider varchar(64) NOT NULL,
            model varchar(128) NOT NULL,
            effective_from timestamptz NOT NULL,
            effective_to timestamptz NULL,
            input_per_million numeric(20,8) NOT NULL CHECK (input_per_million >= 0),
            cached_input_per_million numeric(20,8) NULL
              CHECK (cached_input_per_million IS NULL OR cached_input_per_million >= 0),
            output_per_million numeric(20,8) NOT NULL CHECK (output_per_million >= 0),
            reasoning_per_million numeric(20,8) NULL
              CHECK (reasoning_per_million IS NULL OR reasoning_per_million >= 0),
            currency varchar(3) NOT NULL,
            source varchar(256) NOT NULL,
            refreshed_at timestamptz NOT NULL,
            definition_hash varchar(80) NOT NULL UNIQUE,
            CHECK (effective_to IS NULL OR effective_to > effective_from)
        );
        CREATE INDEX IF NOT EXISTS ix_model_pricing_lookup
          ON domain.model_pricing_versions (provider, model, effective_from DESC);

        ALTER TABLE runtime.model_invocations
          ADD COLUMN IF NOT EXISTS cached_input_tokens bigint NULL
            CHECK (cached_input_tokens IS NULL OR cached_input_tokens >= 0),
          ADD COLUMN IF NOT EXISTS reasoning_tokens bigint NULL
            CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
          ADD COLUMN IF NOT EXISTS total_tokens bigint NULL
            CHECK (total_tokens IS NULL OR total_tokens >= 0),
          ADD COLUMN IF NOT EXISTS usage_estimated boolean NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS provider_usage_version varchar(32) NULL,
          ADD COLUMN IF NOT EXISTS first_token_latency_ms bigint NULL
            CHECK (first_token_latency_ms IS NULL OR first_token_latency_ms >= 0),
          ADD COLUMN IF NOT EXISTS pricing_version_id uuid NULL
            REFERENCES domain.model_pricing_versions(pricing_version_id),
          ADD COLUMN IF NOT EXISTS cost_microusd bigint NULL
            CHECK (cost_microusd IS NULL OR cost_microusd >= 0);
        CREATE INDEX IF NOT EXISTS ix_model_invocations_run_started
          ON runtime.model_invocations (run_id, started_at);

        ALTER TABLE runtime.agent_runs
          ADD COLUMN IF NOT EXISTS accepted_at timestamptz NULL,
          ADD COLUMN IF NOT EXISTS dispatch_started_at timestamptz NULL,
          ADD COLUMN IF NOT EXISTS terminal_at timestamptz NULL,
          ADD COLUMN IF NOT EXISTS response_published_at timestamptz NULL,
          ADD COLUMN IF NOT EXISTS total_cost_microusd bigint NULL
            CHECK (total_cost_microusd IS NULL OR total_cost_microusd >= 0);
        CREATE INDEX IF NOT EXISTS ix_agent_runs_tenant_terminal
          ON runtime.agent_runs (tenant_id, terminal_at DESC);

        GRANT SELECT ON domain.model_pricing_versions TO commerce_agent_runtime;
        GRANT SELECT, INSERT, UPDATE ON runtime.model_invocations, runtime.agent_runs
          TO commerce_agent_runtime;
        """
    )


def downgrade() -> None:
    # Expand-contract rollback: deployed application code may stop using these
    # fields, but downgrade must not destroy already collected usage/cost data
    # or immutable pricing evidence.  A later retention-approved migration can
    # remove the columns/table after archival.  Re-upgrade is idempotent.
    op.execute("DROP INDEX IF EXISTS runtime.ix_agent_runs_tenant_terminal")
    op.execute("DROP INDEX IF EXISTS runtime.ix_model_invocations_run_started")
    op.execute("DROP INDEX IF EXISTS domain.ix_model_pricing_lookup")
