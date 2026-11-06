"""Read-only views of enrolled courses for MCP tools (MCP-B5).

Unlike GetStepView, nothing here finishes attempts, refreshes progress or marks a step
viewed. Blocks are built field by field from an allow-list, so no question, answer or
file id can pass through, whatever a render holds.
"""

from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.revision_loading import (
    load_rendered,
    load_rendered_many,
)
from app.modules.lms.application.learning.step_context import load_live_step
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.domain.learning.entities import Attempt
from app.modules.lms.domain.learning.errors import CourseNotFoundError
from app.modules.lms.domain.learning.live import RenderCache
from app.modules.lms.ports.learning.unit_of_work import LearningUnitOfWork
from app.shared.actor import Actor


def _test_block(block: dict[str, Any], attempts: list[Attempt]) -> dict[str, Any]:
    rules = block["rules"]
    limit = rules["attempts_left"]  # the render holds the limit
    scores = [
        float(a.effective_score)
        for a in attempts
        if a.is_submitted and a.effective_score is not None
    ]
    return {
        "id": block["id"],
        "type": "test",
        "questions": rules["questions"],
        "attempts_left": None if limit is None else max(0, limit - len(attempts)),
        "time_limit_sec": rules["time_limit_sec"],
        "passing_score_pct": rules["passing_score_pct"],
        "best_score_pct": max(scores) if scores else None,
    }


def _block(block: dict[str, Any], attempts: list[Attempt]) -> dict[str, Any]:
    kind = block["type"]
    base = {"id": block["id"], "type": kind}
    if kind == "text":
        return {**base, "markdown": block["markdown"]}
    if kind in ("video", "interactive_video"):
        upload = block.get("source") == "upload"
        return {
            **base,
            "source": block.get("source"),
            "caption": block.get("caption", ""),
            "external_url": None if upload else block.get("url"),
            "has_media_link": upload,
        }
    if kind == "test":
        return _test_block(block, attempts)
    if kind == "flashcards":
        return {**base, "cards_count": block["cards_count"]}
    return base


class LearnerCourseReader:
    """Courses a student is enrolled in; anything else is not found."""

    def __init__(self, uow_factory: UowFactory, cache: RenderCache) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.cache = cache

    async def my_courses(self, actor: Actor) -> list[dict[str, Any]]:
        """Return the open courses the actor is enrolled in, by title."""
        async with self.uow_factory() as uow:
            enrollments = await uow.enrollments.list_for_user(actor.user_id)
            courses = await uow.courses.get_many([e.course_id for e in enrollments])
        progress = {e.course_id: e.progress_pct for e in enrollments}
        rows = [
            {
                "id": course.id,
                "slug": course.slug,
                "title": course.title,
                "summary": course.summary,
                "progress_pct": progress.get(course.id),
            }
            for course in courses
            if course.is_open_for_students
        ]
        return sorted(rows, key=lambda row: str(row["title"]).casefold())

    async def curriculum(self, actor: Actor, course_id: UUID) -> dict[str, Any]:
        """Return the outline of the live version with the actor's completed steps."""
        async with self.uow_factory() as uow:
            await self._require_enrolled(uow, actor, course_id)
            course = await uow.courses.get(course_id)
            version = (
                await uow.versions.get(course.live_version_id)
                if course is not None and course.live_version_id is not None
                else None
            )
            if course is None or version is None:
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            done = await uow.states.completed_step_ids(
                actor.user_id, version.manifest.step_ids()
            )
        return {
            "id": course.id,
            "slug": course.slug,
            "title": course.title,
            "description": course.description,
            "sections": [
                {
                    "id": section.id,
                    "title": section.title,
                    "steps": [
                        {
                            "step_id": step.step_id,
                            "title": step.title,
                            "completed": step.step_id in done,
                        }
                        for step in section.steps
                    ],
                }
                for section in version.manifest.sections
            ],
        }

    async def step(
        self, actor: Actor, course_id: UUID, step_id: UUID
    ) -> dict[str, Any]:
        """Return a step as safe fields; tests are rules and own best score only."""
        async with self.uow_factory() as uow:
            await self._require_enrolled(uow, actor, course_id)
            context = await load_live_step(uow, step_id)
            if context.course.id != course_id:
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            rendered = await load_rendered(
                uow, self.cache, context.live_step.revision_id
            )
            attempts = await uow.attempts.list_for_step(actor.user_id, step_id)
        by_block: dict[str, list[Attempt]] = {}
        for attempt in attempts:
            by_block.setdefault(attempt.block_id, []).append(attempt)
        return {
            "step_id": step_id,
            "course_id": course_id,
            "title": rendered.title,
            "blocks": [
                _block(block, by_block.get(block["id"], []))
                for block in rendered.blocks
            ],
        }

    async def course_file_ids(self, actor: Actor) -> list[tuple[UUID, UUID]]:
        """Return (course, file) of uploaded media in the actor's open courses."""
        found: list[tuple[UUID, UUID]] = []
        async with self.uow_factory() as uow:
            enrollments = await uow.enrollments.list_for_user(actor.user_id)
            courses = await uow.courses.get_many([e.course_id for e in enrollments])
            open_courses = [c for c in courses if c.is_open_for_students]
            versions = await uow.versions.get_many(
                [c.live_version_id for c in open_courses if c.live_version_id]
            )
            for course in open_courses:
                version = (
                    versions.get(course.live_version_id)
                    if course.live_version_id
                    else None
                )
                if version is None:
                    continue
                renders = await load_rendered_many(
                    uow,
                    self.cache,
                    [step.revision_id for step in version.manifest.steps()],
                )
                found.extend(
                    (course.id, UUID(block["file_id"]))
                    for render in renders.values()
                    for block in render.blocks
                    if block.get("source") == "upload" and block.get("file_id")
                )
        return found

    async def _require_enrolled(
        self, uow: LearningUnitOfWork, actor: Actor, course_id: UUID
    ) -> None:
        if await uow.enrollments.get(course_id, actor.user_id) is None:
            raise CourseNotFoundError(params={"course_id": str(course_id)})
