"""Use case: upload an H5P package for a course; it is unpacked into the store."""

import asyncio
from uuid import UUID, uuid4

from app.modules.lms.application.authoring.access import access_to
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.authoring.views import H5PPackageView
from app.modules.lms.domain.authoring.errors import (
    CourseNotFoundError,
    H5PPackageInvalidError,
)
from app.modules.lms.domain.authoring.permissions import EDIT
from app.modules.lms.domain.h5p_package import H5PPackageError, parse_package
from app.modules.lms.domain.h5p_token import package_prefix
from app.modules.lms.ports.h5p_store import H5PObjectStore
from app.shared.actor import Actor

PUT_CONCURRENCY = 8


class UploadH5P:
    """Validate the ``.h5p`` zip, write its files under the course, return its id.

    The package id is random (uuid4) and the package is immutable: a new upload is
    a new package, so published revisions keep playing the files they referenced.
    """

    def __init__(self, uow_factory: UowFactory, store: H5PObjectStore) -> None:
        """Store the unit of work factory and the object store."""
        self.uow_factory = uow_factory
        self.store = store

    async def execute(
        self, actor: Actor, course_id: UUID, data: bytes
    ) -> H5PPackageView:
        """Return the stored package; needs `edit` on the course."""
        async with self.uow_factory() as uow:
            if await uow.courses.get(course_id) is None:
                raise CourseNotFoundError(params={"course_id": str(course_id)})
            (await access_to(uow, actor, course_id)).require(EDIT)
        try:
            package = await asyncio.to_thread(parse_package, data)
        except H5PPackageError as exc:
            raise H5PPackageInvalidError(
                params={"reason": exc.reason}, support_details=exc.detail
            ) from exc
        package_id = uuid4()
        prefix = package_prefix(course_id, package_id)
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
        return H5PPackageView(
            package_id=str(package_id),
            title=package.title,
            main_library=package.main_library,
            files=len(package.entries),
            byte_size=package.byte_size,
        )
