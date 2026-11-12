"""SQLAlchemy Core mirror of the tables created by migration 0001 (LLD B3.6).

The DDL (CHECKs, partial indexes, triggers) lives in the migration; this file only describes the columns the
repositories read and write. Tests compare the two (tests/db/test_schema.py).
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

metadata = MetaData()

ai_summaries = Table(
    "ai_summaries", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("patient_id", UUID(as_uuid=True), nullable=False),
    Column("requested_by", UUID(as_uuid=True), nullable=False),
    Column("request_id", Text),
    Column("force", Boolean, nullable=False, server_default=text("false")),
    Column("status", Text, nullable=False, server_default=text("'running'")),
    Column("cached_from", UUID(as_uuid=True), ForeignKey("ai_summaries.id")),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("schema_version", Text, nullable=False),
    Column("rules_version", Text, nullable=False),
    Column("tools_enabled", Boolean, nullable=False),
    Column("context_hash", Text),
    Column("context_snapshot", JSONB(none_as_null=True)),
    Column("facts", JSONB(none_as_null=True)),
    Column("gaps", JSONB(none_as_null=True)),
    Column("output", JSONB(none_as_null=True)),
    Column("sources", JSONB(none_as_null=True)),
    Column("validation", JSONB(none_as_null=True)),
    Column("progress", JSONB, nullable=False),
    Column("error_code", Text),
    Column("attempts", SmallInteger, nullable=False, server_default=text("0")),
    Column("tool_call_count", SmallInteger, nullable=False, server_default=text("0")),
    Column("tokens_in", Integer),
    Column("tokens_out", Integer),
    Column("latency_ms", Integer),
    Column("started_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("heartbeat_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("finished_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    # Partial indexes are declared only so the mirror documents them; the migration creates them.
    Index("ux_summaries_running", "patient_id", "requested_by", unique=True,
          postgresql_where=text("status = 'running'")),
)

llm_tool_calls = Table(
    "llm_tool_calls", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("summary_id", UUID(as_uuid=True), ForeignKey("ai_summaries.id"), nullable=False),
    Column("seq", SmallInteger, nullable=False),
    Column("iteration", SmallInteger, nullable=False),
    Column("tool_name", Text, nullable=False),
    Column("arguments", JSONB(none_as_null=True), nullable=False, server_default=text("'{}'::jsonb")),
    Column("status", Text, nullable=False),
    Column("error_code", Text),
    Column("result_rows", Integer),
    Column("result_bytes", Integer),
    Column("truncated", Boolean, nullable=False, server_default=text("false")),
    Column("latency_ms", Integer, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)
