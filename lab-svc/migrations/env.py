"""Async Alembic environment. Takes a Postgres advisory lock so two replicas starting together
cannot race on DDL (LLD §15.4)."""
import asyncio
import os

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.session import build_ssl
from app.models import Base

config = context.config
MIGRATION_LOCK_ID = 727_003  # unique per service: auth=727001, patient=727002, lab=727003


def _url() -> str:
    url = os.environ.get("LAB_DATABASE_URL")
    if not url:
        raise RuntimeError("LAB_DATABASE_URL is not set")
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
    # same TLS settings as the application (LAB_DB_SSLMODE / LAB_DB_SSLROOTCERT)
    ssl_arg = build_ssl(os.environ.get("LAB_DB_SSLMODE", "disable"), os.environ.get("LAB_DB_SSLROOTCERT"))
    engine = create_async_engine(_url(), connect_args={"ssl": ssl_arg} if ssl_arg is not None else {})
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported (advisory lock needs a live connection).")
asyncio.run(run_async())
