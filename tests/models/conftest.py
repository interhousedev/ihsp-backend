"""Fixtures for model and migration tests: throw-away PostgreSQL databases."""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_URL = "postgresql+asyncpg://ihsp:ihsp@localhost:5433/ihsp"

DatabaseFactory = Callable[[], Awaitable[str]]


def _server_url() -> URL:
    """Return the URL of the development database server."""
    return make_url(os.environ.get("IHSP_DATABASE__URL", DEFAULT_URL))


async def _execute_on_server(sql: str) -> None:
    """Run one statement on the server's ``postgres`` database."""
    url = _server_url()
    connection = await asyncpg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        database="postgres",
    )
    try:
        await connection.execute(sql)
    finally:
        await connection.close()


def run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``alembic <args>`` against the given database in a subprocess."""
    env = {**os.environ, "IHSP_DATABASE__URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture(scope="session")
async def new_database() -> AsyncIterator[DatabaseFactory]:
    """Yield a factory of empty databases; all are dropped at the end."""
    created: list[str] = []

    async def create() -> str:
        name = f"ihsp_models_{uuid.uuid4().hex[:8]}"
        await _execute_on_server(f'CREATE DATABASE "{name}"')
        created.append(name)
        return _server_url().set(database=name).render_as_string(hide_password=False)

    yield create
    for name in created:
        await _execute_on_server(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
async def migrated_engine(new_database: DatabaseFactory) -> AsyncIterator[AsyncEngine]:
    """An engine on a database created by ``alembic upgrade heads``."""
    url = await new_database()
    await asyncio.to_thread(run_alembic, url, "upgrade", "heads")
    engine = create_async_engine(url)
    yield engine
    await engine.dispose()
