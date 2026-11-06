"""Fake of McpFilesCoursesTools: fixed answers plus a record of the calls."""

from typing import Any
from uuid import UUID

from app.shared.actor import Actor
from app.shared.base_error import NotFoundError
from app.shared.contracts.mcp_files_courses import FileOrigin, VisibleFile


class FakeCourseNotFoundError(NotFoundError):
    """What the LMS raises for a course the actor is not enrolled in."""

    code = "lms/course-not-found"
    message_key = "lms-learn-course-not-found"


class FakeFilesCoursesTools:
    """In memory; a course is visible only when `enrolled` lists it."""

    def __init__(self) -> None:
        self.visible: list[VisibleFile] = []
        self.search_calls: list[tuple[UUID, str]] = []
        self.search_result: dict[str, Any] = {"results": [], "truncated": False}
        self.enrolled: set[UUID] = set()
        self.step: dict[str, Any] = {"title": "Step", "blocks": []}
        self.media: dict[str, Any] = {"links": {}, "media_expires_at": None}

    async def visible_files(
        self,
        actor: Actor,
        *,
        only_personal: bool,
        origin: FileOrigin | None,
        subject_id: UUID | None,
        limit: int,
    ) -> list[VisibleFile]:
        rows = [f for f in self.visible if origin is None or f.origin == origin]
        return rows[:limit]

    async def resolve_file(self, actor: Actor, file_id: UUID) -> VisibleFile | None:
        return next((f for f in self.visible if f.file_id == file_id), None)

    async def search_visible_files(
        self, actor: Actor, query: str, *, only_personal: bool, limit: int
    ) -> dict[str, Any]:
        self.search_calls.append((actor.user_id, query))
        return self.search_result

    async def list_my_courses(self, actor: Actor) -> list[dict[str, Any]]:
        return [{"id": course_id, "title": "Course"} for course_id in self.enrolled]

    async def course_curriculum(self, actor: Actor, course_id: UUID) -> dict[str, Any]:
        self._require(course_id)
        return {"id": course_id, "title": "Course", "sections": []}

    async def course_step(
        self, actor: Actor, course_id: UUID, step_id: UUID
    ) -> dict[str, Any]:
        self._require(course_id)
        return self.step

    async def issue_media_link(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> dict[str, Any]:
        self._require(course_id)
        return self.media

    def _require(self, course_id: UUID) -> None:
        if course_id not in self.enrolled:
            raise FakeCourseNotFoundError(params={"course_id": str(course_id)})
