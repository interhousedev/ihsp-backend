"""Async engine and session factory."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(url: str, pool_size: int) -> AsyncEngine:
    """Create the async engine (lazy: opens no connection)."""
    return create_async_engine(url, pool_size=pool_size, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory; objects stay usable after commit."""
    return async_sessionmaker(engine, expire_on_commit=False)
