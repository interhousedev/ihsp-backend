"""MCP-B4: which files the catalog admits, per origin, over fake modules."""

import datetime as dt
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from app.bootstrap.adapters.mcp_files import McpFileCatalog
from app.shared.actor import Actor, Role
from app.shared.contracts.notebooks_files import NotebookFile
from tests.fakes.clock import FixedClock
from tests.mcp.fakes import (
    FakeLinks,
    FakeSchedule,
    make_file,
    make_lesson,
    make_resource,
)


class _Files:
    def __init__(self, files: list[Any]) -> None:
        self.by_id = {f.id: f for f in files}
        self.searched: list[list[UUID]] = []

    async def list_owned(self, owner_id: UUID, *, limit: int) -> list[Any]:
        return [f for f in self.by_id.values() if f.owner_id == owner_id][:limit]

    async def get_many(self, ids: Any) -> dict[UUID, Any]:  # noqa: ANN401
        return {i: self.by_id[i] for i in ids if i in self.by_id}

    async def search_text_in(
        self, ids: Any, query: str, limit: int  # noqa: ANN401
    ) -> list[dict[str, Any]]:
        self.searched.append(list(ids))
        return [{"file_id": i, "name": "x", "snippet": query} for i in ids][:limit]


class _Links(FakeLinks):
    async def resources_for_lessons(
        self, lesson_ids: Any
    ) -> dict[UUID, list[Any]]:  # noqa: ANN401
        return {i: await self.lesson_resources(i) for i in lesson_ids}


class _Schedule(FakeSchedule):
    async def lessons_for_student(
        self, user_id: UUID, start: date, end: date
    ) -> list[Any]:
        return self.mine


async def _no_courses(_actor: Actor) -> list[tuple[UUID, UUID]]:
    return []


def _catalog(
    files: list[Any],
    *,
    lessons: tuple[Any, ...] = (),
    resources: tuple[Any, ...] = (),
    shared: tuple[UUID, ...] = (),
    notebooks: tuple[NotebookFile, ...] = (),
    courses: tuple[tuple[UUID, UUID], ...] = (),
) -> tuple[McpFileCatalog, _Files]:
    api = _Files(files)
    links = _Links()
    for resource in resources:
        links.resources.setdefault(resource.lesson_id, []).append(resource)
    schedule = _Schedule()
    schedule.mine = list(lessons)

    async def shared_ids(_actor: Actor) -> list[UUID]:
        return list(shared)

    async def notebook_files(_actor: Actor) -> list[NotebookFile]:
        return list(notebooks)

    async def course_files(_actor: Actor) -> list[tuple[UUID, UUID]]:
        return list(courses)

    catalog = McpFileCatalog(
        files=api,  # type: ignore[arg-type]
        links=links,  # type: ignore[arg-type]
        schedule=schedule,  # type: ignore[arg-type]
        shared_file_ids=shared_ids,
        notebook_files=notebook_files,
        course_files=course_files,
        clock=FixedClock(dt.datetime(2026, 11, 5, tzinfo=dt.UTC)),
    )
    return catalog, api


def _student() -> Actor:
    return Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))


async def _ids(
    catalog: McpFileCatalog, actor: Actor, **kw: Any
) -> set[UUID]:  # noqa: ANN401
    params = {"only_personal": False, "origin": None, "subject_id": None, "limit": 100}
    rows = await catalog.visible(actor, **{**params, **kw})
    return {row.file_id for row in rows}


async def test_every_origin_is_admitted_and_labelled() -> None:
    """MCP-B4: personal, lesson, shared, notebook, flashcards and course."""
    actor = _student()
    made = [make_file(actor.user_id)] + [make_file(uuid4()) for _ in range(5)]
    lesson = make_lesson()
    course_id = uuid4()
    catalog, _ = _catalog(
        made,
        lessons=(lesson,),
        resources=(make_resource(lesson.id, kind="file", file_id=made[1].id),),
        shared=(made[2].id,),
        notebooks=(
            NotebookFile(made[3].id, uuid4(), "subject_auto", False),
            NotebookFile(made[4].id, uuid4(), "flashcards", False),
        ),
        courses=((course_id, made[5].id),),
    )
    rows = await catalog.visible(
        actor, only_personal=False, origin=None, subject_id=None, limit=100
    )
    assert {r.file_id: r.origin for r in rows} == {
        made[0].id: "personal",
        made[1].id: "lesson",
        made[2].id: "shared",
        made[3].id: "notebook",
        made[4].id: "flashcards",
        made[5].id: "course",
    }


async def test_only_personal_ignores_everything_else() -> None:
    """MCP-B4: the toggle limits the catalog to own uploads."""
    actor = _student()
    mine, other = make_file(actor.user_id), make_file(uuid4())
    catalog, _ = _catalog([mine, other], shared=(other.id,))
    assert await _ids(catalog, actor, only_personal=True) == {mine.id}


async def test_hidden_resources_and_other_groups_stay_out() -> None:
    """MCP-B4: a hidden resource, and a lesson outside the audience, are not listed."""
    actor = _student()
    hidden, foreign = make_file(uuid4()), make_file(uuid4())
    mine = make_lesson()
    not_mine = make_lesson()
    catalog, _ = _catalog(
        [hidden, foreign],
        lessons=(mine,),
        resources=(
            make_resource(mine.id, kind="file", file_id=hidden.id, hidden=True),
            make_resource(not_mine.id, kind="file", file_id=foreign.id),
        ),
    )
    assert await _ids(catalog, actor) == set()
    assert await catalog.resolve(actor, foreign.id) is None


async def test_subject_filter_keeps_that_subject() -> None:
    """MCP-B4: a subject id narrows to its lessons."""
    actor = _student()
    first, second = make_file(uuid4()), make_file(uuid4())
    subject = uuid4()
    one, two = make_lesson(subject_id=subject), make_lesson(subject_id=uuid4())
    catalog, _ = _catalog(
        [first, second],
        lessons=(one, two),
        resources=(
            make_resource(one.id, kind="file", file_id=first.id),
            make_resource(two.id, kind="file", file_id=second.id),
        ),
    )
    rows = await catalog.visible(
        actor, only_personal=False, origin=None, subject_id=subject, limit=10
    )
    assert [(r.file_id, r.origin) for r in rows] == [(first.id, "subject")]


async def test_files_not_ready_are_dropped() -> None:
    """MCP-B4: a file still processing is not offered."""
    actor = _student()
    busy = make_file(actor.user_id, status="processing")
    catalog, _ = _catalog([busy], shared=(busy.id,))
    assert await _ids(catalog, actor) == set()


async def test_search_only_passes_allowed_ids() -> None:
    """MCP-B4: ids are computed first, so a foreign file is never searched."""
    actor = _student()
    mine, foreign = make_file(actor.user_id), make_file(uuid4())
    catalog, api = _catalog([mine, foreign])
    result = await catalog.search(actor, "ohm", only_personal=False, limit=5)
    assert api.searched == [[mine.id]]
    assert result["truncated"] is False
    assert result["results"][0]["origin"] == "personal"


async def test_search_reports_truncation(monkeypatch: Any) -> None:  # noqa: ANN401
    """MCP-B4: above the cap, the newest files are searched and that is reported."""
    from app.bootstrap.adapters import mcp_files

    monkeypatch.setattr(mcp_files, "CATALOG_CAP", 1)
    actor = _student()
    files = [make_file(actor.user_id), make_file(actor.user_id)]
    catalog, api = _catalog(files)
    result = await catalog.search(actor, "ohm", only_personal=False, limit=5)
    assert result["truncated"] is True
    assert len(api.searched[0]) == 1
