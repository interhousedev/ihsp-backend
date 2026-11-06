"""McpFilesCoursesTools over files, links, notebooks and the LMS.

Sets of flash cards hold no files of their own: their files are the sources of the
hidden notebook of a set, and a shared set arrives as the recipient's own copy.
"""

import datetime as dt
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from app.interfaces.mcp.links import McpLinks
from app.interfaces.mcp.ports import McpFilesApi
from app.modules.lms.application.learning.redeem_media_grant import ConnectorCheck
from app.modules.notebooks.application.visible_source_files import VisibleSourceFiles
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.links import LinksApi
from app.shared.contracts.mcp_files_courses import (
    FileOrigin,
    McpFilesCoursesTools,
    VisibleFile,
)
from app.shared.contracts.notebooks_files import NotebookFile

if TYPE_CHECKING:
    from app.bootstrap.container import Container
    from app.modules.lms.wiring_learning import LearningServices

CATALOG_CAP: Final = 2000
LESSONS_BACK: Final = dt.timedelta(days=730)
LESSONS_AHEAD: Final = dt.timedelta(days=30)
_NOTEBOOK_DETAIL: Final = {
    "subject_auto": "subject",
    "lesson_auto": "subject",
    "course_student": "lms",
    "course": "lms",
    "manual": "custom",
}

SharedIds = Callable[[Actor], Awaitable[list[UUID]]]
NotebookFiles = Callable[[Actor], Awaitable[list[NotebookFile]]]
CourseFiles = Callable[[Actor], Awaitable[list[tuple[UUID, UUID]]]]


class McpFileCatalog:
    """Every file a student may read, each once, with the first reason found."""

    def __init__(
        self,
        *,
        files: McpFilesApi,
        links: LinksApi,
        schedule: ScheduleQueries,
        shared_file_ids: SharedIds,
        notebook_files: NotebookFiles,
        course_files: CourseFiles,
        clock: Clock,
    ) -> None:
        """Store the sources of the catalog."""
        self._files = files
        self._links = links
        self._schedule = schedule
        self._shared_file_ids = shared_file_ids
        self._notebook_files = notebook_files
        self._course_files = course_files
        self._clock = clock

    async def visible(
        self,
        actor: Actor,
        *,
        only_personal: bool,
        origin: FileOrigin | None,
        subject_id: UUID | None,
        limit: int,
    ) -> list[VisibleFile]:
        """The ready files the actor may read, newest first (ids are time ordered)."""
        rows = await self._gather(actor, only_personal, subject_id)
        if origin is not None:
            rows = [row for row in rows if row.origin == origin]
        ready = await self._files.get_many([row.file_id for row in rows])
        kept = [
            row
            for row in rows
            if (file := ready.get(row.file_id)) is not None and file.status == "ready"
        ]
        return sorted(kept, key=lambda row: row.file_id.int, reverse=True)[:limit]

    async def resolve(self, actor: Actor, file_id: UUID) -> VisibleFile | None:
        """Why the actor may read this file; None when they may not."""
        rows = await self._gather(actor, False, None)
        return next((row for row in rows if row.file_id == file_id), None)

    async def search(
        self, actor: Actor, query: str, *, only_personal: bool, limit: int
    ) -> dict[str, Any]:
        """Search within the allowed ids only: foreign text is never even read."""
        rows = await self.visible(
            actor,
            only_personal=only_personal,
            origin=None,
            subject_id=None,
            limit=CATALOG_CAP + 1,
        )
        truncated = len(rows) > CATALOG_CAP
        allowed = {row.file_id: row for row in rows[:CATALOG_CAP]}
        hits = await self._files.search_text_in(list(allowed), query, limit)
        return {
            "results": [
                {**hit, "origin": allowed[hit["file_id"]].origin}
                for hit in hits
                if hit["file_id"] in allowed
            ],
            "truncated": truncated,
        }

    async def _gather(
        self, actor: Actor, only_personal: bool, subject_id: UUID | None
    ) -> list[VisibleFile]:
        owned = await self._files.list_owned(actor.user_id, limit=CATALOG_CAP + 1)
        rows = [VisibleFile(file.id, "personal") for file in owned]
        if only_personal:
            return rows
        if subject_id is not None:
            return _unique(await self._lessons(actor, subject_id))
        rows += [
            VisibleFile(file_id, "shared")
            for file_id in await self._shared_file_ids(actor)
        ]
        rows += await self._lessons(actor, None)
        rows += [_notebook_row(item) for item in await self._notebook_files(actor)]
        rows += [
            VisibleFile(file_id, "course", course_id)
            for course_id, file_id in await self._course_files(actor)
        ]
        return _unique(rows)

    async def _lessons(
        self, actor: Actor, subject_id: UUID | None
    ) -> list[VisibleFile]:
        """Files of the student's own lessons; hidden resources stay out."""
        today = self._clock.now().date()
        lessons = await self._schedule.lessons_for_student(
            actor.user_id, today - LESSONS_BACK, today + LESSONS_AHEAD
        )
        by_id = {
            lesson.id: lesson
            for lesson in lessons
            if subject_id is None or lesson.subject_id == subject_id
        }
        resources = await self._links.resources_for_lessons(list(by_id))
        origin: FileOrigin = "subject" if subject_id else "lesson"
        return [
            VisibleFile(item.file_id, origin, lesson_id, by_id[lesson_id].subject_id)
            for lesson_id, items in resources.items()
            for item in items
            if item.file_id is not None and not item.hidden and lesson_id in by_id
        ]


def _notebook_row(item: NotebookFile) -> VisibleFile:
    if item.origin == "flashcards":
        return VisibleFile(item.file_id, "flashcards", item.notebook_id)
    detail = "shared" if item.shared else _NOTEBOOK_DETAIL.get(item.origin)
    return VisibleFile(item.file_id, "notebook", item.notebook_id, None, detail)


def _unique(rows: list[VisibleFile]) -> list[VisibleFile]:
    seen: dict[UUID, VisibleFile] = {}
    for row in rows:
        seen.setdefault(row.file_id, row)
    return list(seen.values())


class FilesCoursesTools:
    """The contract: the catalog plus the learning side of the LMS."""

    def __init__(
        self, catalog: McpFileCatalog, learning: "LearningServices", settings: Settings
    ) -> None:
        """Store the backends."""
        self._catalog = catalog
        self._learning = learning
        self._settings = settings

    async def visible_files(
        self,
        actor: Actor,
        *,
        only_personal: bool,
        origin: FileOrigin | None,
        subject_id: UUID | None,
        limit: int,
    ) -> list[VisibleFile]:
        """The files the actor may read, newest first."""
        return await self._catalog.visible(
            actor,
            only_personal=only_personal,
            origin=origin,
            subject_id=subject_id,
            limit=limit,
        )

    async def resolve_file(self, actor: Actor, file_id: UUID) -> VisibleFile | None:
        """Why the actor may read this file."""
        return await self._catalog.resolve(actor, file_id)

    async def search_visible_files(
        self, actor: Actor, query: str, *, only_personal: bool, limit: int
    ) -> dict[str, Any]:
        """Search within the allowed ids."""
        return await self._catalog.search(
            actor, query, only_personal=only_personal, limit=limit
        )

    async def list_my_courses(self, actor: Actor) -> list[dict[str, Any]]:
        """Courses the actor is enrolled in."""
        return await self._learning.learner_course_reader.my_courses(actor)

    async def course_curriculum(self, actor: Actor, course_id: UUID) -> dict[str, Any]:
        """Outline of an enrolled course."""
        return await self._learning.learner_course_reader.curriculum(actor, course_id)

    async def course_step(
        self, actor: Actor, course_id: UUID, step_id: UUID
    ) -> dict[str, Any]:
        """A step with no side effects."""
        return await self._learning.learner_course_reader.step(
            actor, course_id, step_id
        )

    async def issue_media_link(
        self, actor: Actor, course_id: UUID, step_id: UUID, block_id: str
    ) -> dict[str, Any]:
        """Rotate the grant; the token goes only in the fragment of the page link."""
        issued = await self._learning.issue_media_grant.execute(
            actor, course_id, step_id, block_id
        )
        links = McpLinks(self._settings).course_step(course_id, step_id)
        if issued.token is None:
            return {
                "kind": "external",
                "links": links,
                "external_url": issued.external_url,
            }
        base = self._settings.urls.lms.rstrip("/")
        return {
            "kind": "grant",
            "links": {**links, "media": f"{base}/media/#t={issued.token}"},
            "media_expires_at": issued.expires_at,
        }


def connector_active_check(container: "Container") -> ConnectorCheck:
    """How the LMS asks whether the connector behind a media link still works."""
    connector_uow = container.identity.auth.uow_factory

    async def connector_active(connector_id: UUID) -> bool:
        async with connector_uow() as uow:
            connector = await uow.connectors.get(connector_id)
        return connector is not None and connector.is_active(container.clock.now())

    return connector_active


def build_files_courses_tools(container: "Container") -> McpFilesCoursesTools:
    """Build the backend of the file catalog and the learner tools."""
    shares = container.files.manage_shares
    notebook_reader = VisibleSourceFiles(container.notebooks.manage_shares.uow_factory)
    learning = container.lms.learning

    async def shared_file_ids(actor: Actor) -> list[UUID]:
        return [file.id for file in await shares.list_shared(actor)]

    async def notebook_files(actor: Actor) -> list[NotebookFile]:
        return await notebook_reader.execute(actor.user_id)

    catalog = McpFileCatalog(
        files=container.files.public,
        links=container.links.public,
        schedule=container.academic.schedule.queries,
        shared_file_ids=shared_file_ids,
        notebook_files=notebook_files,
        course_files=learning.learner_course_reader.course_file_ids,
        clock=container.clock,
    )
    return FilesCoursesTools(catalog, learning, container.settings)
