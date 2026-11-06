"""A1, A3, B2: the adapter over the academic module: isolation, split and job start."""

import datetime as dt
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.bootstrap.adapters.mcp_academic import McpAcademicToolsAdapter
from app.interfaces.mcp.errors import McpNotFoundError
from app.modules.academic.domain.classwork.errors import LessonNotFoundError
from app.modules.academic.domain.schedule.errors import TeacherNotFoundError
from app.modules.academic.infrastructure.schedule.lesson_fetch_store import (
    RedisLessonFetchStore,
)
from app.shared.actor import Actor, Role
from tests.fakes.clock import FixedClock
from tests.mcp.fakes import make_resource

import pytest
from fakeredis.aioredis import FakeRedis


def _actor() -> Actor:
    return Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))


class Kicker:
    def __init__(self, *, fail: bool = False) -> None:
        self.kicks: list[dict[str, Any]] = []
        self.fail = fail

    async def kick(self, task_name: str, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("down")
        self.kicks.append({"task": task_name, **kwargs})


def _adapter(**academic: Any) -> tuple[McpAcademicToolsAdapter, Kicker]:
    kicker = Kicker()
    container = SimpleNamespace(
        redis=FakeRedis(decode_responses=True),
        kicker=kicker,
        clock=FixedClock(),
        academic=SimpleNamespace(**academic),
    )
    return McpAcademicToolsAdapter(container), kicker  # type: ignore[arg-type]


async def test_someone_elses_teacher_is_the_plain_not_found() -> None:
    """A1: a teacher outside the student's groups is not found, as anything missing."""

    async def refuse(*_: Any) -> Any:
        raise TeacherNotFoundError(params={"teacher_id": "x"})

    adapter, _ = _adapter(
        schedule=SimpleNamespace(get_teacher_timetable=SimpleNamespace(execute=refuse))
    )
    with pytest.raises(McpNotFoundError):
        await adapter.teacher_timetable(
            _actor(), uuid4(), dt.date(2026, 1, 1), dt.date(2026, 1, 2)
        )


async def test_someone_elses_lesson_is_the_plain_not_found() -> None:
    """B2: another student's lesson is not found."""

    async def refuse(*_: Any) -> Any:
        raise LessonNotFoundError(params={"lesson_id": "x"})

    adapter, _ = _adapter(
        classwork=SimpleNamespace(student_lesson=SimpleNamespace(execute=refuse))
    )
    with pytest.raises(McpNotFoundError):
        await adapter.lesson_detail(_actor(), uuid4())


async def test_lesson_detail_splits_materials_and_applies_the_hidden_rule() -> None:
    """B2: by kind; others' hidden items are absent, own hidden stay."""
    actor = _actor()
    lesson_id = uuid4()
    someone = uuid4()

    def ref(title: str, **changes: Any) -> Any:
        base = make_resource(lesson_id=lesson_id, title=title)
        return replace(base, **{"author_id": someone, **changes})

    refs = [
        ref("h", material_kind="homework"),
        ref("c", material_kind="classwork"),
        ref("v", material_kind="video"),
        ref("o"),
        ref("role", role="homework"),
        ref("att", role="attachment"),
        ref("hidden", material_kind="classwork", hidden=True),
        ref("mine", hidden=True, author_id=actor.user_id),
    ]

    async def view(*_: Any) -> dict[str, Any]:
        return {
            "lesson": {"id": lesson_id},
            "homework": {"text": "x"},
            "materials": [],
            "attachments": [],
            "my_mark": [],
            "my_attendance": "present",
            "can_attach": True,
        }

    async def lesson_resources(*_: Any, **kwargs: Any) -> list[Any]:
        assert kwargs == {"include_hidden": True}
        return refs

    adapter, _ = _adapter(
        classwork=SimpleNamespace(student_lesson=SimpleNamespace(execute=view))
    )
    adapter._c.links = SimpleNamespace(  # type: ignore[assignment]
        public=SimpleNamespace(lesson_resources=lesson_resources)
    )

    data = await adapter.lesson_detail(actor, lesson_id)

    titles = {
        key: [i["title"] for i in rows] for key, rows in data["materials"].items()
    }
    assert titles == {
        "homework": ["h", "role"],
        "classwork": ["c"],
        "video": ["v"],
        "other": ["o", "mine"],
    }
    assert [i["title"] for i in data["attachments"]] == ["att"]
    assert "can_attach" not in data


async def test_a_new_fetch_kicks_the_task_once() -> None:
    """A3: two callers, one job, one task."""
    adapter, kicker = _adapter()
    adapter._store = RedisLessonFetchStore(FakeRedis(decode_responses=True))
    lesson_id = uuid4()

    first = await adapter.start_material_fetch(uuid4(), lesson_id)
    second = await adapter.start_material_fetch(uuid4(), lesson_id)

    assert first.job_id == second.job_id
    assert len(kicker.kicks) == 1
    assert kicker.kicks[0]["task"] == "academic.fetch_lesson_materials"
    assert kicker.kicks[0]["job_id"] == first.job_id


async def test_a_lost_kick_ends_as_busy() -> None:
    """A3: no task means no waiting."""
    adapter, kicker = _adapter()
    kicker.fail = True
    lesson_id = uuid4()

    fetch = await adapter.start_material_fetch(uuid4(), lesson_id)

    assert (fetch.status, fetch.reason) == ("failed", "emis_busy")
    stored = await adapter.material_fetch(lesson_id)
    assert stored is not None
    assert stored.status == "failed"


async def test_over_the_per_user_cap_is_busy_without_a_task() -> None:
    """A3: a fourth lesson at once is refused."""
    adapter, kicker = _adapter()
    user_id = uuid4()
    for _ in range(3):
        await adapter.start_material_fetch(user_id, uuid4())

    fetch = await adapter.start_material_fetch(user_id, uuid4())

    assert (fetch.status, fetch.reason) == ("failed", "emis_busy")
    assert len(kicker.kicks) == 3


async def test_gpa_joins_the_labelled_temporary_value() -> None:
    """A5: temporary marks stay separate and per subject."""
    subject = uuid4()

    async def results(*_: Any) -> dict[str, Any]:
        return {
            "semester": 3,
            "gpa": 4.5,
            "subjects": [
                {
                    "subject_id": subject,
                    "name": "A",
                    "marks_count": 1,
                    "semester_mark": 4.5,
                }
            ],
        }

    async def summary(*_: Any) -> list[Any]:
        return [SimpleNamespace(subject_id=subject, gpa_with_temporary=4.8)]

    adapter, _ = _adapter(
        marks=SimpleNamespace(
            queries=SimpleNamespace(results=results, subjects_summary=summary)
        )
    )
    data = await adapter.gpa(uuid4(), 3)
    assert data["gpa"] == 4.5
    assert data["subjects"][0]["gpa_with_temporary"] == 4.8
