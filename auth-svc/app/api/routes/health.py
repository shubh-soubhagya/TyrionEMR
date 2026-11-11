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
log = logging.getLogger("auth.health")
_ROOT = Path(__file__).resolve().parents[3]   # auth-svc root (/app in the container)


@lru_cache
def head_revision() -> str:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "migrations"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert head is not None
    return head


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict:
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
    if getattr(request.app.state, "keystore", None) is None:
        failed.append("signing_key")
    if failed:
        raise NotReady(details=[{"check": c, "status": "failed"} for c in failed])
    return {"status": "ready", "db": "ok", "migrations": "head", "signing_key": request.app.state.keystore.active.kid}
