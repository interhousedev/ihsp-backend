"""Cards for UniLibrary records: the stored item's card, else one built from facts."""

from collections.abc import Sequence

from app.modules.library.application.cards import TAG_LABELS, CardBuilder, excerpt
from app.modules.library.application.views import (
    ExternalCardView,
    ItemCardView,
    SubjectView,
)
from app.modules.library.domain.access import can_view
from app.modules.library.domain.enums import ExternalSource, ItemKind
from app.modules.library.domain.external_feed import FieldMapEntry
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.external_catalog import ExternalRecord
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.shared.actor import Actor

SOURCE = ExternalSource.UNILIBRARY


def record_card(
    record: ExternalRecord, subjects: tuple[SubjectView, ...] = ()
) -> ItemCardView:
    """The card of a record that is not stored: no id, no slug, a link-out only."""
    return ItemCardView(
        id=None,
        slug=None,
        kind=ItemKind.EXTERNAL,
        type=record.item_type,
        title=record.title,
        author_label=record.authors,
        language=record.language.value,
        year_published=record.year,
        cover_url=record.cover_url,
        description_excerpt=excerpt(record.description),
        subjects=subjects,
        years_of_study=(),
        has_text=False,
        page_count=record.page_count,
        shelf_state=None,
        progress_percent=None,
        tag_source="unilibrary",
        tag_label=TAG_LABELS["unilibrary"],
        external=ExternalCardView(
            external_id=record.external_id,
            category=record.category,
            access=record.access,
            type_name=record.type_name or "",
            field_name=record.field_name or "",
            view_url=record.view_url,
            gone=False,
        ),
    )


class ExternalCards:
    """Builds cards for records inside an open unit of work.

    A record that is stored (pinned) answers with its item's card (id, slug, the
    viewer's shelf state, our subject tags); one a librarian hid is left out for
    readers; any other gets a card from the facts, with the subject chips of its
    field through the field map.
    """

    def __init__(self, *, cards: CardBuilder, academic: AcademicDirectory) -> None:
        """Take the item card builder and the academic directory."""
        self.cards = cards
        self.academic = academic

    async def build(
        self,
        uow: LibraryUnitOfWork,
        records: Sequence[ExternalRecord],
        *,
        viewer: Actor | None,
        locale: str,
        field_map: Sequence[FieldMapEntry] | None = None,
    ) -> list[ItemCardView]:
        """Cards in the order of the records; hidden ones are missing."""
        ids = await uow.external.item_ids_by_external(
            SOURCE, [r.external_id for r in records]
        )
        stored = await uow.items.get_many(list(ids.values())) if ids else {}
        visible = {
            external_id: stored[item_id]
            for external_id, item_id in ids.items()
            if item_id in stored and can_view(stored[item_id], viewer)
        }
        stored_cards = await self.cards.build(
            uow, list(visible.values()), viewer=viewer, locale=locale
        )
        card_of = dict(zip(visible, stored_cards, strict=True))
        chips = await self._chips(
            uow, [r for r in records if r.external_id not in ids], locale, field_map
        )
        cards: list[ItemCardView] = []
        for record in records:
            if record.external_id in card_of:
                cards.append(card_of[record.external_id])
            elif record.external_id not in ids:
                subjects = chips.get(record.field_id or 0, ())
                cards.append(record_card(record, subjects))
        return cards

    async def _chips(
        self,
        uow: LibraryUnitOfWork,
        records: Sequence[ExternalRecord],
        locale: str,
        field_map: Sequence[FieldMapEntry] | None,
    ) -> dict[int, tuple[SubjectView, ...]]:
        """Subject chips by field id, for the records that need them."""
        if not records:
            return {}
        entries = field_map if field_map is not None else await uow.external.field_map()
        wanted = {r.field_id for r in records if r.field_id}
        relevant = [e for e in entries if e.external_field_id in wanted]
        names = await self.academic.subject_names(
            list({e.subject_id for e in relevant}), locale
        )
        chips: dict[int, list[SubjectView]] = {}
        for entry in relevant:
            if entry.subject_id in names:
                chips.setdefault(entry.external_field_id, []).append(
                    SubjectView(id=entry.subject_id, name=names[entry.subject_id])
                )
        return {field: tuple(views) for field, views in chips.items()}
