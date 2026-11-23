"""Use case: upload a custom HTML widget for a course; it is unpacked into the store."""

import asyncio
from uuid import UUID, uuid4

from app.modules.lms.application.authoring.access import access_to
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import (
    HtmlWidgetFileView,
    HtmlWidgetPackageView,
)
from app.modules.lms.domain.authoring.errors import (
    CourseNotFoundError,
    HtmlWidgetInvalidError,
)
from app.modules.lms.domain.authoring.permissions import EDIT
from app.modules.lms.domain.html_widget import (
    WidgetPackageError,
    parse_widget,
    widget_prefix,
)
from app.modules.lms.ports.h5p_store import H5PObjectStore
from app.shared.actor import Actor

PUT_CONCURRENCY = 8


class UploadHtmlWidget:
    """Validate a ``.html`` file or a ``.zip`` widget, store its files, return its id.

    Like H5P packages, a widget is immutable under a random id: a new upload is a
    new widget, so published revisions keep the files they referenced.
    """

    def __init__(self, uow_factory: UowFactory, store: H5PObjectStore) -> None:
        """Store the unit of work factory and the object store."""
        self.uow_factory = uow_factory
        self.store = store

    async def execute(
        self, actor: Actor, course_id: UUID, data: bytes, filename: str
    ) -> HtmlWidgetPackageView:
        """Return the stored widget; needs `edit` on the course."""
        async with self.uow_factory() as uow:
            if await uow.courses.get(course_id) is None:
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            (await access_to(uow, actor, course_id)).require(EDIT)
        try:
            package = await asyncio.to_thread(parse_widget, data, filename)
        except WidgetPackageError as exc:
            raise HtmlWidgetInvalidError(
                params={"reason": exc.reason}, support_details=exc.detail
            ) from exc
        package_id = uuid4()
        prefix = widget_prefix(course_id, package_id)
        limit = asyncio.Semaphore(PUT_CONCURRENCY)

        async def put(path: str, body: bytes, content_type: str) -> None:
            async with limit:
                await self.store.put(prefix + path, body, content_type)

        try:
            await asyncio.gather(
                *(put(e.path, e.data, e.content_type) for e in package.entries)
            )
        except Exception:
            await self.store.delete_many([prefix + e.path for e in package.entries])
            raise
        files = sorted(package.entries, key=lambda entry: entry.path)
        return HtmlWidgetPackageView(
            package_id=str(package_id),
            files=[
                HtmlWidgetFileView(
                    path=entry.path,
                    byte_size=len(entry.data),
                    content_type=entry.content_type,
                )
                for entry in files
            ],
            file_count=len(files),
            byte_size=package.byte_size,
        )
