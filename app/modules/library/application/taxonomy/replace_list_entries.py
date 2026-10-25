"""Replace all entries of a reading list in one step (LIB-4)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.taxonomy.reading_list_builder import (
    ReadingListBuilder,
)
from app.modules.library.application.taxonomy.views import ReadingListDetailView
from app.modules.library.domain.access import can_view
from app.modules.library.domain.errors import ItemNotFoundError, ListNotFoundError
from app.modules.library.domain.reading_list import (
    EntryDraft,
    ReadingListEntry,
    build_entries,
)
from app.modules.library.domain.reading_list_policy import (
    can_edit_list,
    can_view_list,
)
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_errors import (
    ListEntryInvalidError,
    ListForbiddenError,
)
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import AuditDraft


class ReplaceListEntries:
    """`PUT /v1/library/reading-lists/{id}/items`: at most `list_max_items`."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        identity: IdentityDirectory,
        builder: ReadingListBuilder,
        max_items: int,
        anonymous_cards: bool,
    ) -> None:
        """Store the dependencies and the entry limit."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity
        self.builder = builder
        self.max_items = max_items
        self.anonymous_cards = anonymous_cards

    async def execute(
        self,
        actor: Actor,
        list_id: UUID,
        drafts: Sequence[EntryDraft],
        *,
        accept_language: str | None = None,
    ) -> ReadingListDetailView:
        """Check and store the entries, then answer with the new detail."""
        locale = await resolve_locale(self.identity, actor, accept_language)
        entries = build_entries(drafts, self.max_items)
        async with self.uow_factory() as uow:
            lst = await uow.lists.get(list_id, lock=True)
            if lst is None or not can_view_list(lst, actor, group_id=None):
                raise ListNotFoundError(params={"list_id": str(list_id)})
            if not can_edit_list(lst, actor):
                raise ListForbiddenError(params={"list_id": str(list_id)})
            await self._check_targets(uow, actor, entries)
            await uow.lists.replace_entries(list_id, entries)
            lst.updated_at = self.clock.now()
            await uow.lists.save(lst)
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.LIST_UPDATE.value,
                    actor_id=actor.user_id,
                    metadata={"list_id": str(list_id), "entries": len(entries)},
                )
            )
            await uow.commit()
            return await self.builder.detail_for(uow, lst, viewer=actor, locale=locale)

    async def _check_targets(
        self,
        uow: LibraryUnitOfWork,
        actor: Actor,
        entries: Sequence[ReadingListEntry],
    ) -> None:
        item_ids = list({e.item_id for e in entries if e.item_id is not None})
        found = await uow.items.get_many(item_ids)
        for entry in entries:
            if entry.item_id is None:
                continue
            item = found.get(entry.item_id)
            if item is None or not can_view(
                item, actor, anonymous_cards=self.anonymous_cards
            ):
                raise ItemNotFoundError(params={"item_id": str(entry.item_id)})
        topic_ids = list({e.topic_id for e in entries if e.topic_id is not None})
        if topic_ids and len(await uow.taxonomy.topic_names(topic_ids)) != len(
            topic_ids
        ):
            raise ListEntryInvalidError(params={"position": 0, "reason": "topic"})
