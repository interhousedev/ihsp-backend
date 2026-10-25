"""Async engine and session factory."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_MAX_OVERFLOW = 5
DEFAULT_POOL_TIMEOUT_SECONDS = 10.0
DEFAULT_STATEMENT_TIMEOUT_MS = 30_000


def make_engine(
    url: str,
    pool_size: int,
    *,
    max_overflow: int = DEFAULT_MAX_OVERFLOW,
    pool_timeout: float = DEFAULT_POOL_TIMEOUT_SECONDS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> AsyncEngine:
    """Create the async engine (lazy: opens no connection).

    `max_overflow` bounds the burst connections above `pool_size`, `pool_timeout`
    is how long a request waits for a free connection, and every connection runs
    with PostgreSQL's `statement_timeout` so one runaway query cannot hold it.
    """
    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {"statement_timeout": str(statement_timeout_ms)}
        },
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory; objects stay usable after commit."""
    return async_sessionmaker(engine, expire_on_commit=False)
