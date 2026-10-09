"""Edit title, description, topics or text of a material (LIB-13)."""

from uuid import UUID

from app.modules.library.application.detail import DetailBuilder, ItemDetailView
from app.modules.library.application.materials.drafts import (
    DESCRIPTION_MAX,
    TITLE_MAX,
    MaterialDrafts,
)
from app.modules.library.application.materials.inputs import MaterialPatch
from app.modules.library.application.materials.loading import load_editable
from app.modules.library.application.materials.search_text import build_search_text
from app.modules.library.domain.access import is_owner
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import EventKind, ItemStatus
from app.modules.library.domain.errors import NotEditableError
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError, ValidationFailedError
from app.shared.clock import Clock

CLOSED = frozenset({ItemStatus.REJECTED, ItemStatus.UNPUBLISHED, ItemStatus.GONE})
ATTESTABLE = frozenset({ItemStatus.DRAFT, ItemStatus.CHANGES_REQUESTED})


class UpdateMaterial:
    """The owner (or a librarian) edits a material that is still in play."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        drafts: MaterialDrafts,
        detail: DetailBuilder,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.drafts = drafts
        self.detail = detail

    async def execute(
        self, actor: Actor, item_id: UUID, patch: MaterialPatch, *, locale: str
    ) -> ItemDetailView:
        """Apply the fields that are set; the status never changes."""
        async with self.uow_factory() as uow:
            item = await load_editable(uow, item_id, actor, lock=True)
            if item.status in CLOSED:
                raise NotEditableError(params={"status": item.status.value})
            changed = await self._apply(uow, item, patch, actor)
            if changed:
                item.updated_at = self.clock.now()
                item.search_text = build_search_text(item)
                await uow.items.save(item)
                await uow.events.append(
                    item.id,
                    EventKind.EDITED,
                    at=item.updated_at,
                    actor_id=actor.user_id,
                    data={"fields": changed},
                )
            view = await self.detail.build(uow, item, viewer=actor, locale=locale)
            await uow.commit()
        return view

    async def _apply(
        self, uow: LibraryUnitOfWork, item: Item, patch: MaterialPatch, actor: Actor
    ) -> list[str]:
        """Set the given fields on the item; return the names that changed."""
        changed = self._apply_texts(item, patch)
        if patch.attested is not None:
            self._apply_attestation(item, patch.attested, actor)
            changed.append("attested")
        if patch.topic_ids is not None:
            await self.drafts.check_topics(uow, patch.topic_ids)
            await self.drafts.set_topics(uow, item.id, patch.topic_ids)
            changed.append("topic_ids")
        if patch.body_md is not None and patch.body_md.strip():
            await self.drafts.set_body(uow, item, patch.body_md)
            changed.append("body_md")
        return changed

    @staticmethod
    def _apply_texts(item: Item, patch: MaterialPatch) -> list[str]:
        changed: list[str] = []
        if patch.title is not None:
            title = patch.title.strip()
            if not title or len(title) > TITLE_MAX:
                raise ValidationFailedError(params={"field": "title"})
            item.title = title
            changed.append("title")
        if patch.description is not None:
            description = patch.description.strip()
            if len(description) > DESCRIPTION_MAX:
                raise ValidationFailedError(params={"field": "description"})
            item.description = description or None
            changed.append("description")
        return changed

    def _apply_attestation(self, item: Item, attested: bool, actor: Actor) -> None:
        """Only the owner attests, and only before the review (draft, sent back)."""
        if item.material is None or not is_owner(item, actor):
            raise ForbiddenError(support_details="only the owner attests")
        if item.status not in ATTESTABLE:
            raise NotEditableError(params={"status": item.status.value})
        item.material.attested_at = self.clock.now() if attested else None
