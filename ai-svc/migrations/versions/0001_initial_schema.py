"""Initial schema: ai_summaries, llm_tool_calls, indexes, immutability triggers (LLD B3).

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# One statement per op.execute: asyncpg prepares each statement, so a multi-statement string is rejected.
STATEMENTS = [
    """
CREATE TABLE ai_summaries (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id        uuid        NOT NULL,
    requested_by      uuid        NOT NULL,
    request_id        text        NULL CHECK (request_id IS NULL OR char_length(request_id) <= 128),
    force             boolean     NOT NULL DEFAULT false,
    status            text        NOT NULL DEFAULT 'running',
    cached_from       uuid        NULL REFERENCES ai_summaries(id),
    provider          text        NOT NULL CHECK (provider IN ('mock','gemini','groq','ollama')),
    model             text        NOT NULL CHECK (char_length(model) BETWEEN 1 AND 120),
    prompt_version    text        NOT NULL CHECK (prompt_version ~ '^v[0-9]+$'),
    schema_version    text        NOT NULL,
    rules_version     text        NOT NULL,
    tools_enabled     boolean     NOT NULL,
    context_hash      text        NULL,
    context_snapshot  jsonb       NULL,
    facts             jsonb       NULL,
    gaps              jsonb       NULL,
    output            jsonb       NULL,
    sources           jsonb       NULL,
    validation        jsonb       NULL,
    progress          jsonb       NOT NULL,
    error_code        text        NULL,
    attempts          smallint    NOT NULL DEFAULT 0,
    tool_call_count   smallint    NOT NULL DEFAULT 0,
    tokens_in         integer     NULL CHECK (tokens_in  IS NULL OR tokens_in  >= 0),
    tokens_out        integer     NULL CHECK (tokens_out IS NULL OR tokens_out >= 0),
    latency_ms        integer     NULL CHECK (latency_ms IS NULL OR latency_ms >= 0),
    started_at        timestamptz NOT NULL DEFAULT now(),
    heartbeat_at      timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT status_values   CHECK (status IN ('running','completed','degraded','failed')),
    CONSTRAINT finish_iff_terminal CHECK ((status = 'running') = (finished_at IS NULL)),
    CONSTRAINT hash_format     CHECK (context_hash IS NULL OR context_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT not_self_cached CHECK (cached_from IS DISTINCT FROM id),
    CONSTRAINT counters        CHECK (attempts BETWEEN 0 AND 10 AND tool_call_count BETWEEN 0 AND 50),
    CONSTRAINT progress_array  CHECK (jsonb_typeof(progress) = 'array'),

    CONSTRAINT completed_original_shape CHECK (
        status <> 'completed' OR cached_from IS NOT NULL OR (
            output IS NOT NULL AND facts IS NOT NULL AND gaps IS NOT NULL
            AND sources IS NOT NULL AND validation IS NOT NULL AND context_hash IS NOT NULL)),
    CONSTRAINT cache_hit_shape CHECK (
        cached_from IS NULL OR (status = 'completed' AND output IS NULL AND attempts = 0)),
    CONSTRAINT degraded_shape CHECK (
        status <> 'degraded' OR (facts IS NOT NULL AND gaps IS NOT NULL AND output IS NULL AND error_code IS NOT NULL)),
    CONSTRAINT failed_shape CHECK (
        status <> 'failed' OR (error_code IS NOT NULL AND output IS NULL)),
    CONSTRAINT error_code_values CHECK (error_code IS NULL OR error_code IN (
        'UPSTREAM_UNAVAILABLE','UPSTREAM_TIMEOUT','PATIENT_NOT_FOUND',
        'LLM_TIMEOUT','LLM_UNAVAILABLE','LLM_RATE_LIMITED','LLM_CIRCUIT_OPEN','LLM_BUSY',
        'LLM_INVALID_OUTPUT','JOB_TIMEOUT','JOB_ABORTED','INTERNAL_ERROR'))
)""",
    # AI-ADR-2: one running job per patient and clinician
    """CREATE UNIQUE INDEX ux_summaries_running ON ai_summaries (patient_id, requested_by)
    WHERE status = 'running'""",
    # history: originals only, newest first (HLD 5.5)
    """CREATE INDEX ix_summaries_history ON ai_summaries (patient_id, created_at DESC)
    WHERE status IN ('completed','degraded') AND cached_from IS NULL""",
    # cache lookup: completed originals by hash (AI-ADR-3)
    """CREATE INDEX ix_summaries_cache ON ai_summaries (patient_id, context_hash, created_at DESC)
    WHERE status = 'completed' AND cached_from IS NULL""",
    # daily quota count
    """CREATE INDEX ix_summaries_quota ON ai_summaries (requested_by, created_at)
    WHERE cached_from IS NULL""",
    # reaper
    "CREATE INDEX ix_summaries_reaper ON ai_summaries (heartbeat_at) WHERE status = 'running'",
    """
CREATE TABLE llm_tool_calls (
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    summary_id    uuid        NOT NULL REFERENCES ai_summaries(id),
    seq           smallint    NOT NULL CHECK (seq >= 1),
    iteration     smallint    NOT NULL CHECK (iteration >= 1),
    tool_name     text        NOT NULL CHECK (tool_name ~ '^[a-z_]{1,64}$'),
    arguments     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status        text        NOT NULL CHECK (status IN ('ok','error','rejected')),
    error_code    text        NULL,
    result_rows   integer     NULL CHECK (result_rows  IS NULL OR result_rows  >= 0),
    result_bytes  integer     NULL CHECK (result_bytes IS NULL OR result_bytes >= 0),
    truncated     boolean     NOT NULL DEFAULT false,
    latency_ms    integer     NOT NULL CHECK (latency_ms >= 0),
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ux_tool_calls_seq UNIQUE (summary_id, seq),
    CONSTRAINT args_small CHECK (pg_column_size(arguments) <= 4096)
)""",
    """
CREATE FUNCTION ai_summaries_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ai_summaries rows are never deleted'
            USING ERRCODE = 'P0001', HINT = 'NO_DELETE';
    END IF;
    IF OLD.status <> 'running' THEN
        RAISE EXCEPTION 'summary % is final (%)', OLD.id, OLD.status
            USING ERRCODE = 'P0001', HINT = 'SUMMARY_FINAL';
    END IF;
    IF NEW.patient_id <> OLD.patient_id OR NEW.requested_by <> OLD.requested_by
       OR NEW.created_at <> OLD.created_at OR NEW.started_at <> OLD.started_at THEN
        RAISE EXCEPTION 'identity columns of a summary are immutable'
            USING ERRCODE = 'P0001', HINT = 'IMMUTABLE_COLUMN';
    END IF;
    RETURN NEW;
END $$""",
    """CREATE TRIGGER trg_ai_summaries_guard BEFORE UPDATE OR DELETE ON ai_summaries
    FOR EACH ROW EXECUTE FUNCTION ai_summaries_guard()""",
    """
CREATE FUNCTION llm_tool_calls_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE s text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'llm_tool_calls is append-only' USING ERRCODE = 'P0001', HINT = 'APPEND_ONLY';
    END IF;
    SELECT status INTO s FROM ai_summaries WHERE id = NEW.summary_id;
    IF s IS DISTINCT FROM 'running' THEN
        RAISE EXCEPTION 'summary % is not running', NEW.summary_id USING ERRCODE = 'P0001', HINT = 'SUMMARY_FINAL';
    END IF;
    RETURN NEW;
END $$""",
    """CREATE TRIGGER trg_llm_tool_calls_guard BEFORE INSERT OR UPDATE OR DELETE ON llm_tool_calls
    FOR EACH ROW EXECUTE FUNCTION llm_tool_calls_guard()""",
]


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    # Local use only: terminal rows are immutable in production.
    op.execute("DROP TRIGGER IF EXISTS trg_llm_tool_calls_guard ON llm_tool_calls")
    op.execute("DROP TRIGGER IF EXISTS trg_ai_summaries_guard ON ai_summaries")
    op.execute("DROP TABLE IF EXISTS llm_tool_calls")
    op.execute("DROP TABLE IF EXISTS ai_summaries")
    op.execute("DROP FUNCTION IF EXISTS llm_tool_calls_guard()")
    op.execute("DROP FUNCTION IF EXISTS ai_summaries_guard()")
