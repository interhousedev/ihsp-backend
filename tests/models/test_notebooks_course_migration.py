"""notebooks_0003: course workspaces, up and down (LMS-AI 3.2)."""

import asyncio

from tests.models.conftest import DatabaseFactory, run_alembic

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

COURSE = "11111111-1111-1111-1111-111111111111"


async def _alembic(url: str, *args: str) -> None:
    """Run alembic without blocking the event loop."""
    await asyncio.to_thread(run_alembic, url, *args)


async def _run(url: str, sql: str) -> object:
    """Run one statement in its own transaction; return the first value, if any."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql))
            return result.scalar() if result.returns_rows else None
    finally:
        await engine.dispose()


def _notebook(origin: str, course_id: str | None = None) -> str:
    """INSERT of a notebook row (only the columns without defaults)."""
    course = f"'{course_id}'" if course_id else "NULL"
    return (
        "INSERT INTO notebooks.notebooks (id, owner_id, title, origin, course_id) "
        f"VALUES (gen_random_uuid(), gen_random_uuid(), 'T', '{origin}', {course}) "
        "RETURNING id"
    )


def _notebook_0002(origin: str) -> str:
    """INSERT of a notebook row before `course_id` exists."""
    return (
        "INSERT INTO notebooks.notebooks (id, owner_id, title, origin) "
        f"VALUES (gen_random_uuid(), gen_random_uuid(), 'T', '{origin}')"
    )


def _artifact(notebook_id: object, kind: str) -> str:
    """INSERT of an output of the notebook."""
    return (
        "INSERT INTO notebooks.artifacts (id, notebook_id, owner_id, kind, title) "
        f"VALUES (gen_random_uuid(), '{notebook_id}', gen_random_uuid(), '{kind}', "
        "'Plan')"
    )


async def test_0003_adds_course_workspaces_and_takes_them_back(
    new_database: DatabaseFactory,
) -> None:
    """LMS-AI 3.2: origin `course` with a course id, one live per course, course
    kinds; the downgrade deletes the workspaces and forbids them again."""
    url = await new_database()
    await _alembic(url, "upgrade", "notebooks_0002")
    await _run(url, _notebook_0002("manual"))
    with pytest.raises(DBAPIError):
        await _run(url, _notebook_0002("course"))

    await _alembic(url, "upgrade", "notebooks@head")
    workspace = await _run(url, _notebook("course", COURSE))
    await _run(url, _artifact(workspace, "course_plan"))
    await _run(url, _artifact(workspace, "lesson_draft"))
    with pytest.raises(DBAPIError):
        await _run(url, _notebook("course", COURSE))  # one live workspace a course
    with pytest.raises(DBAPIError):
        await _run(url, _notebook("course"))  # a workspace needs its course
    with pytest.raises(DBAPIError):
        await _run(url, _notebook("manual", COURSE))  # only workspaces have one

    await _alembic(url, "downgrade", "notebooks_0002")
    assert await _run(url, "SELECT count(*) FROM notebooks.notebooks") == 1
    assert await _run(url, "SELECT count(*) FROM notebooks.artifacts") == 0
    with pytest.raises(DBAPIError):
        await _run(url, _notebook_0002("course"))
