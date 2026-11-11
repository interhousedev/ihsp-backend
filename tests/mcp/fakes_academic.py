"""Fake of McpAcademicTools: scripted answers, and a record of what was started."""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.shared.actor import Actor
from app.shared.contracts.mcp_academic import MaterialFetch


class FakeAcademicTools:
    """In-memory backend of the academic tools."""

    def __init__(self) -> None:
        self.fetches: dict[UUID, MaterialFetch] = {}
        # What material_fetch answers next, one per read, before `fetches`.
        self.script: list[MaterialFetch] = []
        self.next_fetch: MaterialFetch | None = None
        self.started: list[tuple[UUID, UUID]] = []
        self.refresh_answer: dict[str, Any] = {"status": "queued"}
        self.status_answer: dict[str, Any] = {"status": "never"}
        self.teachers: list[dict[str, Any]] = []
        self.timetable_calls: list[tuple[UUID, UUID, date, date]] = []
        self.gpa_answer: dict[str, Any] = {"semester": 3, "gpa": 4.5, "subjects": []}
        self.details: dict[tuple[UUID, UUID], dict[str, Any]] = {}
        self.names: dict[UUID, str] = {}
        self.calls: list[tuple[Any, ...]] = []

    async def request_refresh(self, actor: Actor) -> dict[str, Any]:
        self.calls.append(("request_refresh", actor.user_id))
        return self.refresh_answer

    async def submit_homework(
        self,
        actor: Actor,
        lesson_id: UUID,
        file_ids: Sequence[UUID],
        comment: str | None,
    ) -> dict[str, Any]:
        self.calls.append(("submit_homework", actor, lesson_id, file_ids, comment))
        return {"lesson_id": str(lesson_id), "status": "submitted"}

    async def withdraw_homework_submission(self, actor: Actor, lesson_id: UUID) -> None:
        self.calls.append(("withdraw_homework_submission", actor, lesson_id))

    async def sync_status(self, user_id: UUID) -> dict[str, Any]:
        self.calls.append(("sync_status", user_id))
        return self.status_answer

    async def my_teachers(self, actor: Actor) -> list[dict[str, Any]]:
        self.calls.append(("my_teachers", actor.user_id))
        return self.teachers

    async def teacher_timetable(
        self, actor: Actor, teacher_id: UUID, start: date, end: date
    ) -> list[dict[str, Any]]:
        self.timetable_calls.append((actor.user_id, teacher_id, start, end))
        return [{"subject_name": "Algebra", "mine": True}]

    async def gpa(self, user_id: UUID, semester: int | None) -> dict[str, Any]:
        self.calls.append(("gpa", user_id))
        return self.gpa_answer

    async def lesson_detail(self, actor: Actor, lesson_id: UUID) -> dict[str, Any]:
        return self.details[(actor.user_id, lesson_id)]

    async def teacher_names(self, teacher_ids: list[UUID]) -> dict[UUID, str]:
        return {key: self.names[key] for key in teacher_ids if key in self.names}

    async def start_material_fetch(
        self, user_id: UUID, lesson_id: UUID
    ) -> MaterialFetch:
        self.started.append((user_id, lesson_id))
        assert self.next_fetch is not None
        self.fetches[lesson_id] = self.next_fetch
        return self.next_fetch

    async def material_fetch(self, lesson_id: UUID) -> MaterialFetch | None:
        if self.script:
            return self.script.pop(0)
        return self.fetches.get(lesson_id)


def running(started_at: datetime, job_id: str = "a" * 32) -> MaterialFetch:
    """A fetch under way."""
    return MaterialFetch(job_id=job_id, status="running", started_at=started_at)
