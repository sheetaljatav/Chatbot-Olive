from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from ..config import settings


def make_engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url, pool_size=10, max_overflow=20, pool_pre_ping=True
    )


def make_sessionmaker(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False)
