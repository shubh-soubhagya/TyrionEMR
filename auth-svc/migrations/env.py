"""Async Alembic environment. Takes a Postgres advisory lock so two replicas starting together
cannot race on DDL (LLD §15.4)."""
import asyncio
import os

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base

config = context.config
MIGRATION_LOCK_ID = 727_001  # unique per service: auth=727001, patient=727002, ...


def _url() -> str:
    url = os.environ.get("AUTH_DATABASE_URL")
    if not url:
        raise RuntimeError("AUTH_DATABASE_URL is not set")
    return url


def do_run_migrations(connection) -> None:
    connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_ID})
    connection.commit()  # end the autobegun transaction so Alembic manages its own
    try:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.rollback()
        connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_ID})
        connection.commit()


async def run_async() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported (advisory lock needs a live connection).")
asyncio.run(run_async())
