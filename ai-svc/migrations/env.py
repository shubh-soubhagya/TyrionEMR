"""Async Alembic environment. Takes a Postgres advisory lock so two replicas starting together cannot race
on DDL (LLD B3.6). The schema is hand-written SQL (triggers and partial indexes are invisible to autogenerate)."""
import asyncio
import os

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.session import build_ssl

config = context.config
MIGRATION_LOCK_ID = 727_004  # auth=727001, patient=727002, lab=727003, ai=727004


def _url() -> str:
    return os.environ.get("AI_DATABASE_URL") or get_settings().ai_database_url


def do_run_migrations(connection) -> None:
    connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_ID})
    connection.commit()  # end the autobegun transaction so Alembic manages its own
    try:
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.rollback()
        connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_ID})
        connection.commit()


async def run_async() -> None:
    ssl_arg = build_ssl(os.environ.get("AI_DB_SSLMODE", "disable"), os.environ.get("AI_DB_SSLROOTCERT"))
    engine = create_async_engine(_url(), connect_args={"ssl": ssl_arg} if ssl_arg is not None else {})
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported (advisory lock needs a live connection).")
asyncio.run(run_async())
