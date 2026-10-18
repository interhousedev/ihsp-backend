"""Source kind `lesson_resource`: a material or attachment of a lesson (§ 3.2.1)."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.application.readers.base import (
    ResolvedSource,
    SourceText,
    clean_title,
    expect_input,
)
from app.modules.notebooks.application.readers.file_reader import (
    FileReader,
    file_id_of,
    require_text,
)
from app.modules.notebooks.application.readers.url_reader import UrlReader
from app.modules.notebooks.domain.auto_notebook import lesson_ref_key
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceFailure, SourceKind
from app.modules.notebooks.domain.errors import (
    SourceForbiddenError,
    SourceReadError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.source_input import (
    LessonResourceInput,
    SourceInput,
)
from app.shared.contracts.academic import LessonRef, ScheduleQueries
from app.shared.contracts.files import FilesApi
from app.shared.contracts.links import LinksApi, ResourceRef


class LessonResourceReader:
    """Materials of lessons the student attends; files and links are read as usual."""

    def __init__(
        self,
        *,
        links: LinksApi,
        schedule: ScheduleQueries,
        files: FilesApi,
        file_reader: FileReader,
        url_reader: UrlReader,
    ) -> None:
        """Store the collaborators."""
        self.links = links
        self.schedule = schedule
        self.files = files
        self.file_reader = file_reader
        self.url_reader = url_reader

    async def resolve(self, user_id: UUID, source_input: SourceInput) -> ResolvedSource:
        """The student attends the lesson and the resource is not hidden."""
        item = expect_input(source_input, LessonResourceInput)
        if not await self.schedule.is_in_audience(user_id, item.lesson_id):
            raise SourceForbiddenError()
        resource = await self._resource(item.lesson_id, item.link_id)
        lesson = await self.schedule.get_lesson(item.lesson_id)
        if resource is None or lesson is None:
            raise SourceForbiddenError()
        return await self.describe(resource, lesson)

    async def describe(
        self, resource: ResourceRef, lesson: LessonRef, *, from_classmates: bool = False
    ) -> ResolvedSource:
        """The source of a resource the caller already checked the student may see.

        Raises:
            SourceUnsupportedError: A file without text (yet), or a link without a
                web fetcher.
        """
        ref = {"lesson_id": str(lesson.id), "link_id": str(resource.link_id)}
        ref.update(await self._target(resource))
        origin: dict[str, Any] = {
            "subject": lesson.subject_name,
            "lesson_date": lesson.date.isoformat(),
            "topic": lesson.topic,
            "role": resource.role,
        }
        if from_classmates:
            origin["from_classmates"] = True
            origin["author"] = resource.author_first_name
        # "14.10 Classwork: <name>": the lesson's day, then the material's own name.
        day = lesson.date.strftime("%d.%m")
        return ResolvedSource(
            kind=SourceKind.LESSON_RESOURCE,
            title=clean_title(
                f"{day} {clean_title(resource.title, 'Lesson material')}", ""
            ),
            ref=ref,
            ref_key=lesson_ref_key(resource.link_id),
            origin=origin,
        )

    async def read(self, source: Source) -> SourceText:
        """A file is read like a `file` source, a link like a `url` source."""
        file_id = file_id_of(source)
        if file_id is not None:
            return await self.file_reader.read_file(file_id)
        url = source.ref.get("url")
        if not url:
            raise SourceReadError(SourceFailure.DELETED.value)
        return await self.url_reader.fetch(str(url))

    async def _resource(self, lesson_id: UUID, link_id: UUID) -> ResourceRef | None:
        """The visible resource with this link id."""
        resources = await self.links.lesson_resources(lesson_id)
        return next(
            (r for r in resources if r.link_id == link_id and not r.hidden), None
        )

    async def _target(self, resource: ResourceRef) -> dict[str, str]:
        """``file_id`` of a file resource (it must have text) or ``url`` of a link.

        A link is read at its target: its short URL opens the link page of IHT
        (title and a button), whose text is not the material.
        """
        if resource.kind == "file" and resource.file_id is not None:
            stored = await self.files.get(resource.file_id)
            if stored is None or stored.status == "deleted":
                raise SourceUnsupportedError(params={"hint": "not_ready"})
            require_text(stored)
            return {"file_id": str(resource.file_id)}
        self.url_reader.require_fetcher()
        return {"url": resource.target_url or resource.short_url}
