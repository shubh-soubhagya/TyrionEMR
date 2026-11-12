import ssl

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import Settings


def build_ssl(mode: str, rootcert: str | None) -> ssl.SSLContext | str | None:
    """asyncpg ``ssl`` argument for LAB_DB_SSLMODE / LAB_DB_SSLROOTCERT (shared by app, CLI and Alembic)."""
    if mode == "disable":
        return None
    if mode == "require":
        if not rootcert:
            return "require"                       # encrypted, certificate not verified
        ctx = ssl.create_default_context(cafile=rootcert)
        ctx.check_hostname = False                 # chain is verified, host name is not (libpq verify-ca)
        return ctx
    if mode == "verify-full":                      # chain AND host name
        return ssl.create_default_context(cafile=rootcert or None)
    raise ValueError(f"unsupported LAB_DB_SSLMODE {mode!r}")


def create_engine(s: Settings) -> AsyncEngine:
    connect_args: dict = {
        "timeout": 3,
        "server_settings": {
            "application_name": "lab-svc",
            "timezone": "UTC",
            "statement_timeout": str(s.db_statement_timeout_ms),
            "lock_timeout": str(s.db_lock_timeout_ms),
            "idle_in_transaction_session_timeout": str(s.db_idle_in_transaction_timeout_ms),
        },
    }
    ssl_arg = build_ssl(s.lab_db_sslmode, s.lab_db_sslrootcert)
    if ssl_arg is not None:
        connect_args["ssl"] = ssl_arg
    return create_async_engine(
        s.lab_database_url,
        pool_size=s.lab_db_pool_size,
        max_overflow=s.lab_db_max_overflow,
        pool_timeout=s.db_pool_timeout_s,
        pool_pre_ping=True,
        pool_recycle=1800,
        # application_name makes our connections easy to spot in pg_stat_activity on the shared container
        connect_args=connect_args,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
