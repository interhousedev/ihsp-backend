"""Alembic environment: async engine, one Alembic branch per module.

Nothing may run on the connection before ``context.configure``: Alembic would then
stop committing. ``CREATE SCHEMA`` therefore lives in each module's first revision.
"""

import asyncio
from logging.config import fileConfig
from typing import Any

from app.settings import load_settings
from app.shared.db.base import Base
from app.shared.db.models import MODULES  # noqa: F401  (registers every model)

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
SCHEMAS = {
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
    "dashboard",
    "knowledge",
    "posts",
    "feedback",
}
# `alembic -x schema=academic revision --autogenerate ...` limits the diff to a schema.
SCHEMA_FILTER: str | None = context.get_x_argument(as_dictionary=True).get("schema")
VERSION_SCHEMA = "public"


def include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
    """Only reflect the module schemas (hides public and system schemas)."""
    if type_ == "schema":
        return name in SCHEMAS
    return True


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """With -x schema=<name>, autogenerate sees only that schema's objects."""
    if SCHEMA_FILTER is None:
        return True
    table = obj if type_ == "table" else getattr(obj, "table", None)
    return bool(table is None or table.schema == SCHEMA_FILTER)


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    return url if url else load_settings().database.url


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        version_table_schema=VERSION_SCHEMA,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Render SQL without a database connection."""
    _configure(
        url=_database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations on a sync connection."""
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open an async engine, then run the migrations through run_sync."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Use a connection passed by code, or create an engine."""
    connection = config.attributes.get("connection")
    if connection is None:
        asyncio.run(run_async_migrations())
    else:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
