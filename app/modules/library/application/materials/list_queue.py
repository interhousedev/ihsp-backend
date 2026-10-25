"""The librarian queue: to review, reports, held, rights, suggestions (doc § 3.6)."""

from collections.abc import Sequence
from datetime import datetime

from app.modules.library.application.cards import TAG_LABELS, CardBuilder
from app.modules.library.application.materials.attribution import attribute
from app.modules.library.application.materials.views import (
    QueueKind,
    QueueRowView,
    QueueTab,
    ReportCountView,
    Slice,
    SuggestionView,
    UploaderView,
)
from app.modules.library.application.views import ItemCardView
from app.modules.library.domain.access import is_librarian
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemKind, ItemType, UploaderRole
from app.modules.library.domain.moderation_entities import BookSuggestion, ReportGroup
from app.modules.library.domain.moderation_rules import needs_rights_attention
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.moderation_repository import QueueEntry
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError, ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.pagination import decode_cursor, encode_cursor


def decode_offset(cursor: str | None) -> int:
    """The row offset a queue cursor stands for (0 for the first page)."""
    data = decode_cursor(cursor)
    if data is None:
        return 0
    offset = data.get("o")
    if not isinstance(offset, int) or offset < 0:
        raise ValidationFailedError(params={"field": "cursor"})
    return offset


class ListQueue:
    """Rows are oldest first; the cursor is an offset (queues are short)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        cards: CardBuilder,
        identity: IdentityDirectory,
        academic: AcademicDirectory,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.cards = cards
        self.identity = identity
        self.academic = academic

    async def execute(
        self,
        actor: Actor,
        tab: QueueTab,
        *,
        cursor: str | None,
        limit: int,
        locale: str,
    ) -> Slice[QueueRowView]:
        """One page of the tab."""
        if not is_librarian(actor):
            raise ForbiddenError(params={"roles": ["librarian", "admin"]})
        offset = decode_offset(cursor)
        async with self.uow_factory() as uow:
            if tab is QueueTab.SUGGESTIONS:
                rows, more = await self._suggestions(uow, actor, limit, offset, locale)
            else:
                rows, more = await self._items(uow, actor, tab, limit, offset, locale)
        return Slice(rows, encode_cursor({"o": offset + limit}) if more else None)

    # - - - Tabs of items - - -

    async def _entries(
        self, uow: LibraryUnitOfWork, tab: QueueTab, limit: int, offset: int
    ) -> list[QueueEntry]:
        """`limit + 1` entries from `offset`, so the caller can tell if more follow."""
        if tab is QueueTab.REVIEW:
            return await uow.moderation.review_queue(limit=limit + 1, offset=offset)
        if tab is QueueTab.RIGHTS:
            return await self._rights(uow, limit, offset)
        return await uow.moderation.report_queue(
            held=tab is QueueTab.HELD, limit=limit + 1, offset=offset
        )

    async def _rights(
        self, uow: LibraryUnitOfWork, limit: int, offset: int
    ) -> list[QueueEntry]:
        """Books to look at: few enough to filter in Python (the rule is dates)."""
        ids = await uow.moderation.rights_candidates()
        now = self.clock.now()
        found = await uow.items.get_many(ids)
        flagged = [
            QueueEntry(item.id, item.created_at)
            for item_id in ids
            if (item := found.get(item_id)) is not None
            and item.book is not None
            and needs_rights_attention(item.book, now)
        ]
        return flagged[offset : offset + limit + 1]

    async def _items(
        self,
        uow: LibraryUnitOfWork,
        actor: Actor,
        tab: QueueTab,
        limit: int,
        offset: int,
        locale: str,
    ) -> tuple[list[QueueRowView], bool]:
        entries = await self._entries(uow, tab, limit, offset)
        more = len(entries) > limit
        entries = entries[:limit]
        ids = [entry.item_id for entry in entries]
        found = await uow.items.get_many(ids)
        items = [found[i] for i in ids if i in found]
        at = {entry.item_id: entry.at for entry in entries}
        cards = await self.cards.build(uow, items, viewer=actor, locale=locale)
        groups = await uow.moderation.report_groups(ids)
        with_reports = tab in {QueueTab.REPORTS, QueueTab.HELD}
        rows = [
            self._row(item, card, tab, at[item.id], groups, with_reports)
            for item, card in zip(items, cards, strict=True)
        ]
        return rows, more

    @staticmethod
    def _row(
        item: Item,
        card: ItemCardView,
        tab: QueueTab,
        when: datetime,
        groups: Sequence[ReportGroup],
        with_reports: bool,
    ) -> QueueRowView:
        mine = [g for g in groups if g.item_id == item.id]
        counts = sorted(mine, key=lambda g: (-g.count, g.first_at))
        material = item.material
        return QueueRowView(
            item=card,
            kind=_kind(item, tab),
            findings=_findings(item),
            reports=tuple(ReportCountView(g.reason, g.count) for g in counts),
            submitted_at=when,
            uploader=(
                UploaderView(
                    material.uploader_name,
                    material.uploader_cohort,
                    material.uploader_role.value,
                )
                if material
                else None
            ),
            report_ids=(
                tuple(i for g in mine for i in g.report_ids) if with_reports else None
            ),
        )

    # - - - Suggestions - - -

    async def _suggestions(
        self, uow: LibraryUnitOfWork, actor: Actor, limit: int, offset: int, locale: str
    ) -> tuple[list[QueueRowView], bool]:
        found = await uow.moderation.new_suggestions(limit=limit + 1, offset=offset)
        more = len(found) > limit
        users = await self.identity.get_users([s.user_id for s in found[:limit]])
        rows = []
        for suggestion in found[:limit]:
            roles = (
                users[suggestion.user_id].roles
                if suggestion.user_id in users
                else frozenset()
            )
            who = await attribute(
                self.identity, self.academic, suggestion.user_id, roles
            )
            rows.append(_suggestion_row(suggestion, who.label))
        return rows, more


def _kind(item: Item, tab: QueueTab) -> QueueKind:
    if tab is QueueTab.RIGHTS:
        return "rights"
    if tab is not QueueTab.REVIEW:
        return "report"
    teacher = (
        item.material is not None
        and item.material.uploader_role is UploaderRole.TEACHER
    )
    return "teacher_material" if teacher else "student_material"


def _findings(item: Item) -> tuple[str, ...]:
    if item.material is None:
        return ()
    findings = item.material.scan.get("findings", [])
    return tuple(str(f) for f in findings) if isinstance(findings, list) else ()


def _suggestion_row(suggestion: BookSuggestion, user_name: str) -> QueueRowView:
    card = ItemCardView(
        id=None,
        slug=None,
        kind=ItemKind.BOOK,
        type=ItemType.OTHER,
        title=suggestion.title,
        author_label=", ".join(
            str(a) for a in (suggestion.details or {}).get("authors", [])
        ),
        language="other",
        year_published=None,
        cover_url=None,
        description_excerpt=None,
        subjects=(),
        years_of_study=(),
        has_text=False,
        page_count=None,
        shelf_state=None,
        progress_percent=None,
        tag_source="book",
        tag_label=TAG_LABELS["book"],
    )
    return QueueRowView(
        item=card,
        kind="suggestion",
        findings=(),
        reports=(),
        submitted_at=suggestion.created_at,
        suggestion=SuggestionView(
            id=suggestion.id,
            title=suggestion.title,
            url=suggestion.url,
            note=suggestion.note,
            user_name=user_name,
            details=suggestion.details,
        ),
    )
