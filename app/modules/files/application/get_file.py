"""Read one file's metadata (owner or administrator)."""

from uuid import UUID

from app.modules.files.application.access import require_readable
from app.modules.files.application.file_views import FileView, FileViewBuilder
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class GetFile:
    """Return a FileView after the access check."""

    def __init__(self, *, uow_factory: UowFactory, views: FileViewBuilder) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._views = views

    async def execute(self, actor: Actor, file_id: UUID) -> FileView:
        """Return the file; NotFound for strangers, Gone when it was deleted."""
        async with self._uow_factory() as uow:
            file = require_readable(await uow.files.get(file_id), actor)
        return await self._views.build_one(file)
