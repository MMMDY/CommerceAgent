"""Add Phase 5 reproducibility and Judge metadata to evaluation tables.

Revision ID: 20260915_0010
Revises: 20260914_0009
"""
from alembic import op

revision = "20260915_0010"
down_revision = "20260914_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the original columns backwards compatible while adding immutable
    # attempt and provenance fields used by the Phase 5 harness.
    op.execute("""
        ALTER TABLE evaluation.eval_runs
          ADD COLUMN IF NOT EXISTS dataset_version varchar(64),
          ADD COLUMN IF NOT EXISTS agent_model varchar(128),
          ADD COLUMN IF NOT EXISTS agent_model_config_hash varchar(80),
          ADD COLUMN IF NOT EXISTS agent_prompt_hash varchar(80),
          ADD COLUMN IF NOT EXISTS judge_model varchar(128),
          ADD COLUMN IF NOT EXISTS judge_prompt_hash varchar(80),
          ADD COLUMN IF NOT EXISTS runtime_versions_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          ADD COLUMN IF NOT EXISTS concurrency integer NOT NULL DEFAULT 1,
          ADD COLUMN IF NOT EXISTS case_timeout_seconds integer NOT NULL DEFAULT 30,
          ADD COLUMN IF NOT EXISTS summary_json jsonb;
        ALTER TABLE evaluation.eval_case_results
          ADD COLUMN IF NOT EXISTS attempt_no integer NOT NULL DEFAULT 1,
          ADD COLUMN IF NOT EXISTS execution_status varchar(16) NOT NULL DEFAULT 'succeeded',
          ADD COLUMN IF NOT EXISTS hard_score numeric(6,5) NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS agent_response_redacted text,
          ADD COLUMN IF NOT EXISTS trace_ref varchar(256),
          ADD COLUMN IF NOT EXISTS latency_ms bigint,
          ADD COLUMN IF NOT EXISTS token_usage_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          ADD COLUMN IF NOT EXISTS final_pass boolean;
        ALTER TABLE evaluation.judge_results
          ADD COLUMN IF NOT EXISTS judge_attempt_no integer NOT NULL DEFAULT 1,
          ADD COLUMN IF NOT EXISTS rubric_id varchar(64),
          ADD COLUMN IF NOT EXISTS rubric_version varchar(32),
          ADD COLUMN IF NOT EXISTS input_hash varchar(80),
          ADD COLUMN IF NOT EXISTS dimension_scores_json jsonb,
          ADD COLUMN IF NOT EXISTS critical_violations_json jsonb,
          ADD COLUMN IF NOT EXISTS judge_pass boolean,
          ADD COLUMN IF NOT EXISTS latency_ms bigint,
          ADD COLUMN IF NOT EXISTS token_usage_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          ADD COLUMN IF NOT EXISTS error_code varchar(64);
        ALTER TABLE evaluation.judge_results
          DROP CONSTRAINT IF EXISTS judge_results_eval_run_id_case_id_fkey;
        ALTER TABLE evaluation.eval_case_results
          DROP CONSTRAINT IF EXISTS eval_case_results_pkey;
        ALTER TABLE evaluation.judge_results
          DROP CONSTRAINT IF EXISTS judge_results_pkey;
        ALTER TABLE evaluation.eval_case_results
          ADD CONSTRAINT eval_case_results_pkey PRIMARY KEY (eval_run_id, case_id, attempt_no);
        ALTER TABLE evaluation.judge_results
          ADD CONSTRAINT judge_results_pkey PRIMARY KEY (eval_run_id, case_id, judge_attempt_no),
          ADD CONSTRAINT judge_results_case_fk FOREIGN KEY (eval_run_id, case_id, judge_attempt_no)
            REFERENCES evaluation.eval_case_results (eval_run_id, case_id, attempt_no);
        CREATE INDEX IF NOT EXISTS ix_eval_case_results_track_fail
          ON evaluation.eval_case_results (eval_run_id, track, hard_pass, case_id);
    """)


def downgrade() -> None:
    # Columns are intentionally retained on downgrade to avoid destructive
    # loss of recorded evaluation provenance; the index can be removed safely.
    op.execute("DROP INDEX IF EXISTS evaluation.ix_eval_case_results_track_fail")
