"""llm_tool_calls access (append-only, LLD B3.3). Arguments and result sizes are stored, never results."""
from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import llm_tool_calls as t

_NAME = re.compile(r"^[a-z_]{1,64}$")


def safe_tool_name(name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """A tool name the model invented is stored as 'unknown', with the raw name truncated into
    ``arguments._name``, so the trace stays readable without trusting model text in a constrained column."""
    if _NAME.match(name):
        return name, arguments
    return "unknown", {**arguments, "_name": name[:64]}


async def append(session: AsyncSession, *, summary_id: uuid.UUID, seq: int, iteration: int, tool_name: str,
                 arguments: dict[str, Any], status: str, latency_ms: int, error_code: str | None = None,
                 result_rows: int | None = None, result_bytes: int | None = None, truncated: bool = False) -> None:
    name, args = safe_tool_name(tool_name, arguments)
    await session.execute(insert(t).values(
        summary_id=summary_id, seq=seq, iteration=iteration, tool_name=name, arguments=args, status=status,
        error_code=error_code, result_rows=result_rows, result_bytes=result_bytes, truncated=truncated,
        latency_ms=latency_ms))


async def list_for(session: AsyncSession, summary_id: uuid.UUID) -> Sequence[Mapping[str, Any]]:
    stmt = select(t).where(t.c.summary_id == summary_id).order_by(t.c.seq)
    return (await session.execute(stmt)).mappings().all()
