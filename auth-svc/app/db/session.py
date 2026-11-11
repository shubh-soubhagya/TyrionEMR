from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import Settings


def create_engine(s: Settings) -> AsyncEngine:
    return create_async_engine(
        s.auth_database_url,
        pool_size=s.auth_db_pool_size,
        max_overflow=s.auth_db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        # application_name makes our connections easy to spot in pg_stat_activity on the shared container
        connect_args={"timeout": 3, "server_settings": {"application_name": "auth-svc"}},
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
