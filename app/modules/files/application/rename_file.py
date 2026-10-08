"""Rename a file (the extension and the storage key never change)."""

from uuid import UUID

from app.modules.files.application.access import require_owner_editable
from app.modules.files.application.file_views import FileView, FileViewBuilder
from app.modules.files.domain.errors import TypeNotAllowedError
from app.modules.files.domain.policy import extension_of, normalize_name
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class RenameFile:
    """Change the display name of the owner's file."""

    def __init__(
        self, *, uow_factory: UowFactory, views: FileViewBuilder, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._views = views
        self._clock = clock

    async def execute(self, actor: Actor, file_id: UUID, name: str) -> FileView:
        """Validate the new name and save it."""
        clean = normalize_name(name)
        async with self._uow_factory() as uow:
            file = require_owner_editable(await uow.files.get(file_id), actor)
            if extension_of(clean) != extension_of(file.name):
                raise TypeNotAllowedError(params={"extension": extension_of(clean)})
            file.rename(clean, self._clock.now())
            await uow.files.save(file)
            await uow.commit()
        return await self._views.build_one(file)
