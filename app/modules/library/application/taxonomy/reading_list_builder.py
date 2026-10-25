"""Shared steps of the reading list use cases: who sees what, and the read models."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.taxonomy.views import (
    PersonView,
    ReadingListCardView,
    ReadingListDetailView,
    ReadingListEntryView,
)
from app.modules.library.application.views import SubjectView
from app.modules.library.domain.access import can_view
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ShelfState
from app.modules.library.domain.reading_list import (
    ReadingList,
    ReadingListEntry,
    essential_progress,
    read_state,
)
from app.modules.library.domain.reading_list_policy import can_edit_list
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class ReadingListBuilder:
    """Builds cards and details of reading lists for one viewer."""

    def __init__(
        self,
        *,
        identity: IdentityDirectory,
        academic: AcademicDirectory,
        cards: CardBuilder,
        anonymous_cards: bool,
    ) -> None:
        """Store the directories and the card builder."""
        self.identity = identity
        self.academic = academic
        self.cards = cards
        self.anonymous_cards = anonymous_cards

    async def _visible_items(
        self,
        uow: LibraryUnitOfWork,
        entries_by_list: dict[UUID, list[ReadingListEntry]],
        viewer: Actor,
    ) -> dict[UUID, Item]:
        """The items of the entries that the viewer may see."""
        ids = list(
            {e.item_id for es in entries_by_list.values() for e in es if e.item_id}
        )
        found = await uow.items.get_many(ids)
        return {
            item_id: item
            for item_id, item in found.items()
            if can_view(item, viewer, anonymous_cards=self.anonymous_cards)
        }

    @staticmethod
    def _shown(
        entries: Sequence[ReadingListEntry], visible: dict[UUID, Item]
    ) -> list[ReadingListEntry]:
        """Links always show; an item entry shows only when the viewer sees the item."""
        return [e for e in entries if e.item_id is None or e.item_id in visible]

    async def cards_for(
        self,
        uow: LibraryUnitOfWork,
        lists: Sequence[ReadingList],
        *,
        viewer: Actor,
        locale: str,
    ) -> list[ReadingListCardView]:
        """Cards in the order given; counts are of the entries the viewer may see."""
        if not lists:
            return []
        entries_by_list = await uow.lists.entries([lst.id for lst in lists])
        visible = await self._visible_items(uow, entries_by_list, viewer)
        states = await uow.shelf.states(viewer.user_id, list(visible))
        owners = await self.identity.get_users(list({lst.owner_id for lst in lists}))
        subject_ids = [lst.subject_id for lst in lists if lst.subject_id]
        names = await self.academic.subject_names(subject_ids, locale)
        views: list[ReadingListCardView] = []
        for lst in lists:
            shown = self._shown(entries_by_list.get(lst.id, []), visible)
            essential, done = essential_progress(shown, states)
            owner = owners.get(lst.owner_id)
            views.append(
                ReadingListCardView(
                    id=lst.id,
                    title=lst.title,
                    description=lst.description,
                    scope=lst.scope,
                    status=lst.status,
                    subject=(
                        SubjectView(id=lst.subject_id, name=names[lst.subject_id])
                        if lst.subject_id and lst.subject_id in names
                        else None
                    ),
                    year_of_study=lst.year_of_study,
                    academic_year=lst.academic_year,
                    term_half=lst.term_half,
                    owner=PersonView(
                        id=lst.owner_id,
                        name=(
                            f"{owner.first_name} {owner.last_name}".strip()
                            if owner
                            else ""
                        ),
                    ),
                    entry_count=len(shown),
                    essential_count=essential,
                    essential_done=done,
                    updated_at=lst.updated_at,
                )
            )
        return views

    async def detail_for(
        self,
        uow: LibraryUnitOfWork,
        reading_list: ReadingList,
        *,
        viewer: Actor,
        locale: str,
    ) -> ReadingListDetailView:
        """The list with its visible entries, cards and the viewer's read states."""
        entries_by_list = await uow.lists.entries([reading_list.id])
        visible = await self._visible_items(uow, entries_by_list, viewer)
        shown = self._shown(entries_by_list.get(reading_list.id, []), visible)
        states: dict[UUID, ShelfState] = await uow.shelf.states(
            viewer.user_id, list(visible)
        )
        cards = await self.cards.build(
            uow, list(visible.values()), viewer=viewer, locale=locale
        )
        by_item = {card.id: card for card in cards if card.id is not None}
        (card_view,) = await self.cards_for(
            uow, [reading_list], viewer=viewer, locale=locale
        )
        entries = tuple(
            ReadingListEntryView(
                position=e.position,
                item=by_item.get(e.item_id) if e.item_id else None,
                url=e.url,
                title=e.title,
                importance=e.importance,
                page_from=e.page_from,
                page_to=e.page_to,
                week_label=e.week_label,
                due_on=e.due_on,
                topic_id=e.topic_id,
                note=e.note,
                read_state=read_state(e, states),
            )
            for e in shown
        )
        return ReadingListDetailView(
            card=card_view,
            group_ids=tuple(reading_list.group_ids),
            entries=entries,
            can_edit=can_edit_list(reading_list, viewer),
        )
