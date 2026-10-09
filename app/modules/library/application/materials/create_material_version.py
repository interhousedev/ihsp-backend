"""Start a new version of a published material (LIB-13)."""

from uuid import UUID

from app.modules.library.application.detail import DetailBuilder, ItemDetailView
from app.modules.library.application.materials.drafts import MaterialDrafts
from app.modules.library.application.materials.inputs import MaterialData
from app.modules.library.application.materials.loading import load_owned
from app.modules.library.domain.enums import ItemStatus
from app.modules.library.domain.errors import NotEditableError
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class CreateMaterialVersion:
    """A new draft that replaces the old version once it is approved."""

    def __init__(
        self, *, uow_factory: UowFactory, drafts: MaterialDrafts, detail: DetailBuilder
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.drafts = drafts
        self.detail = detail

    async def execute(
        self, actor: Actor, item_id: UUID, data: MaterialData, *, locale: str
    ) -> ItemDetailView:
        """Create the version; the old one stays published until the new one is."""
        async with self.uow_factory() as uow:
            old = await load_owned(uow, item_id, actor, lock=True)
            if old.status is not ItemStatus.PUBLISHED:
                raise NotEditableError(params={"status": old.status.value})
            if await uow.moderation.open_versions(old.id):
                raise NotEditableError(params={"status": "version-open"})
            item = await self.drafts.build(uow, actor, data, supersedes_id=old.id)
            view = await self.detail.build(uow, item, viewer=actor, locale=locale)
            await uow.commit()
        return view
