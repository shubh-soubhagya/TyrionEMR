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
log = logging.getLogger("lab.health")
_SOURCE_ROOT = Path(__file__).resolve().parents[3]   # lab-svc/ when running from the source tree


def _project_root() -> Path:
    """Where alembic.ini + migrations live: the working directory in the container (/app, where the app
    itself is installed into site-packages), the source tree when running from a checkout."""
    for candidate in (Path.cwd(), _SOURCE_ROOT):
        if (candidate / "alembic.ini").is_file():
            return candidate
    raise RuntimeError("alembic.ini not found (expected in the working directory)")


@lru_cache
def head_revision() -> str | None:
    """Head revision of the migrations folder; None while no revision exists yet (Phase 2 -> 3)."""
    root = _project_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


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
    jwks = getattr(request.app.state, "jwks", None)
    if jwks is None or jwks.key_count == 0:     # cannot verify tokens without auth-svc's keys
        failed.append("jwks")
    if failed:
        raise NotReady(details=[{"check": c, "status": "failed"} for c in failed])
    return {"status": "ready", "db": "ok", "migrations": "head", "jwks": request.app.state.jwks.key_count}
