"""Start a new draft material (LIB-13)."""

from app.modules.library.application.detail import DetailBuilder, ItemDetailView
from app.modules.library.application.materials.drafts import MaterialDrafts
from app.modules.library.application.materials.inputs import MaterialData
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


class CreateMaterial:
    """Store a draft with the uploader's attribution snapshot; nothing is shared yet."""

    def __init__(
        self, *, uow_factory: UowFactory, drafts: MaterialDrafts, detail: DetailBuilder
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.drafts = drafts
        self.detail = detail

    async def execute(
        self, actor: Actor, data: MaterialData, *, locale: str
    ) -> ItemDetailView:
        """Create the draft and return its detail (status `draft`)."""
        async with self.uow_factory() as uow:
            item = await self.drafts.build(uow, actor, data)
            view = await self.detail.build(uow, item, viewer=actor, locale=locale)
            await uow.commit()
        return view
