"""Helpers that create schemas and tables in a test database."""

from collections.abc import Sequence

from app.shared.db import models  # noqa: F401  (registers every model)
from app.shared.db.base import Base

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

SCHEMAS = (
    "id",
    "academic",
    "files",
    "links",
    "ai",
    "notify",
    "admin",
    "mail",
    "lms",
    "notebooks",
    "library",
    "vectors",
    "certificates",
    "knowledge",
)


def admin_url(database_url: str) -> str:
    """The same server, database `postgres` (used to create and drop databases)."""
    return (
        make_url(database_url)
        .set(database="postgres")
        .render_as_string(hide_password=False)
    )


def database_name(database_url: str) -> str:
    """Name of the database in the URL."""
    name = make_url(database_url).database
    if name is None:
        raise ValueError("database URL has no database name")
    return name


async def create_database(database_url: str) -> None:
    """CREATE DATABASE for the URL's database name (connects to `postgres`)."""
    engine = create_async_engine(admin_url(database_url), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            name = database_name(database_url)  # from the test URL, not user input
            # nosemgrep: avoid-sqlalchemy-text -- name from test DB URL setting
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def drop_database(database_url: str) -> None:
    """DROP DATABASE ... WITH (FORCE) for the URL's database name."""
    engine = create_async_engine(admin_url(database_url), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            name = database_name(database_url)
            # nosemgrep: avoid-sqlalchemy-text -- name from test DB URL setting
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await engine.dispose()


async def create_tables(
    engine: AsyncEngine, schemas: Sequence[str] | None = None
) -> None:
    """Create extensions, schemas and the tables of the given schemas (all by default).

    A module can create only its own schemas when another module's ORM is broken:
    ``await create_tables(engine, schemas=["academic"])``.
    """
    wanted = tuple(SCHEMAS if schemas is None else schemas)
    tables = [t for t in Base.metadata.sorted_tables if t.schema in wanted]
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        for schema in wanted:
            # nosemgrep: avoid-sqlalchemy-text -- schema names are constants
            await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        await conn.run_sync(Base.metadata.create_all, tables=tables)
