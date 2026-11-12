from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from sqlalchemy import text

from app.core.errors import NotReady

router = APIRouter(tags=["health"])
log = logging.getLogger("ai.health")
_SOURCE_ROOT = Path(__file__).resolve().parents[2]


def _project_root() -> Path:
    for candidate in (Path.cwd(), _SOURCE_ROOT):
        if (candidate / "alembic.ini").is_file():
            return candidate
    raise RuntimeError("alembic.ini not found (expected in the working directory)")


@lru_cache
def head_revision() -> str | None:
    """Head revision of the migrations folder; None while no revision exists yet."""
    root = _project_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict:
    """DB answers, migrations at head, JWKS loaded. Upstreams and the LLM are NOT checks (B12.9):
    insights must stay up without the LLM."""
    failed: list[str] = []
    try:
        async with request.app.state.sessionmaker() as s:
            await s.execute(text("SELECT 1"))
            try:
                version = (await s.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            except Exception:
                version = None
        if version != head_revision():
            failed.append("migrations")
    except Exception as exc:     # never leak connection details to the caller
        log.warning("ready.db_failed", extra={"error_type": type(exc).__name__})
        failed += ["db", "migrations"]
    jwks = getattr(request.app.state, "jwks", None)
    if jwks is None or jwks.key_count == 0:
        failed.append("jwks")
    if failed:
        raise NotReady(details=[{"check": c, "status": "failed"} for c in failed])
    return {"status": "ready", "db": "ok", "migrations": "head", "jwks": request.app.state.jwks.key_count}
