"""LIB-13, LIB-14: the SQL repository of reports, sanctions, suggestions and queues."""

import datetime as dt
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    ItemStatus,
    ReportReason,
    ReportStatus,
    Rights,
    SanctionKind,
    SuggestionStatus,
    UploaderRole,
)
from app.modules.library.domain.moderation_entities import (
    BookSuggestion,
    Report,
    Sanction,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.ids import new_id
from tests.factories.library import NOW, make_book, make_material

import pytest
from sqlalchemy.exc import IntegrityError

StoreItem = Callable[[Item], Awaitable[Item]]
HOUR = dt.timedelta(hours=1)


def pending(minutes: int, uploader: UUID | None = None) -> Item:
    """A material submitted `minutes` after the factory time."""
    when = NOW + dt.timedelta(minutes=minutes)
    item = make_material(
        title=f"Notes {minutes}",
        status=ItemStatus.PENDING_REVIEW,
        uploader_id=uploader,
        now=when,
    )
    assert item.material is not None
    item.material.submitted_at = when
    return item


def draft(uploader: UUID | None = None, title: str = "Draft") -> Item:
    """A material that was never submitted."""
    item = make_material(title=title, status=ItemStatus.DRAFT, uploader_id=uploader)
    assert item.material is not None
    item.material.submitted_at = None
    return item


def report(
    item: Item,
    *,
    reason: ReportReason = ReportReason.COPYRIGHT,
    reporter: UUID | None = None,
    at: dt.datetime = NOW,
    role: UploaderRole = UploaderRole.STUDENT,
) -> Report:
    """An open report about the item."""
    return Report(
        id=new_id(),
        item_id=item.id,
        reporter_id=reporter or new_id(),
        reporter_role=role,
        reason=reason,
        created_at=at,
    )


# - - - Reports - - -


async def test_open_reports_come_back_oldest_first(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: reports of an item are stored with reporter, role and reason."""
    item = await store_item(make_material())
    late = report(item, at=NOW + HOUR)
    early = report(item, reason=ReportReason.EXAM_LEAK, role=UploaderRole.TEACHER)

    async with uow_factory() as uow:
        await uow.moderation.add_report(late)
        await uow.moderation.add_report(early)
        await uow.commit()
    async with uow_factory() as uow:
        loaded = await uow.moderation.open_reports(item.id)

    assert [r.id for r in loaded] == [early.id, late.id]
    assert loaded[0].reporter_role is UploaderRole.TEACHER
    assert loaded[0].reason is ReportReason.EXAM_LEAK
    assert loaded[0].status is ReportStatus.OPEN


async def test_one_open_report_per_reporter_and_reason(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: the same person cannot file the same reason twice while it is open."""
    item = await store_item(make_material())
    me = new_id()
    first = report(item, reporter=me)

    async with uow_factory() as uow:
        await uow.moderation.add_report(first)
        again = await uow.moderation.has_open_report(item.id, me, "copyright")
        other_reason = await uow.moderation.has_open_report(item.id, me, "spam")

    assert again is True
    assert other_reason is False


async def test_a_second_identical_open_report_violates_the_unique_index(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: the database backs the one-open-report rule."""
    item = await store_item(make_material())
    me = new_id()

    with pytest.raises(IntegrityError):
        async with uow_factory() as uow:
            await uow.moderation.add_report(report(item, reporter=me))
            await uow.moderation.add_report(report(item, reporter=me))


async def test_closing_reports_marks_all_open_ones_and_frees_the_slot(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: a decision closes every open report of the item at once."""
    item = await store_item(make_material())
    me, handler = new_id(), new_id()
    async with uow_factory() as uow:
        await uow.moderation.add_report(report(item, reporter=me))
        await uow.moderation.add_report(report(item, reason=ReportReason.SPAM))
        closed = await uow.moderation.close_reports(
            item.id,
            ReportStatus.UPHELD,
            handled_by=handler,
            at=NOW + HOUR,
            action="unpublish",
        )
        still_open = await uow.moderation.open_reports(item.id)
        # A closed report no longer blocks the same reporter from reporting again.
        await uow.moderation.add_report(report(item, reporter=me))

    assert closed == 2
    assert still_open == []


async def test_report_groups_count_open_reports_per_reason(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: the queue shows counts per reason, never the reporters."""
    item = await store_item(make_material())
    other = await store_item(make_material(title="Other"))
    async with uow_factory() as uow:
        await uow.moderation.add_report(report(item, at=NOW + HOUR))
        await uow.moderation.add_report(report(item, at=NOW))
        await uow.moderation.add_report(report(item, reason=ReportReason.SPAM))
        await uow.moderation.add_report(report(other))
        groups = await uow.moderation.report_groups([item.id])

    by_reason = {g.reason: g for g in groups}
    assert set(by_reason) == {ReportReason.COPYRIGHT, ReportReason.SPAM}
    assert by_reason[ReportReason.COPYRIGHT].count == 2
    assert by_reason[ReportReason.COPYRIGHT].first_at == NOW
    assert len(by_reason[ReportReason.COPYRIGHT].report_ids) == 2
    assert {g.item_id for g in groups} == {item.id}


async def test_report_times_serve_the_daily_limit(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: the reports a person filed since a moment, whatever their status."""
    item = await store_item(make_material())
    me = new_id()
    async with uow_factory() as uow:
        await uow.moderation.add_report(report(item, reporter=me, at=NOW - 2 * HOUR))
        await uow.moderation.add_report(
            report(item, reporter=me, reason=ReportReason.SPAM, at=NOW)
        )
        await uow.moderation.add_report(report(item))
        times = await uow.moderation.report_times(me, NOW - HOUR)

    assert times == [NOW]


# - - - Sanctions - - -


def sanction(
    kind: SanctionKind, user: UUID, until: dt.datetime | None = None
) -> Sanction:
    """A sanction set by an admin at the factory time."""
    return Sanction(
        id=new_id(),
        user_id=user,
        kind=kind,
        reason="repeated copyright reports",
        set_by=new_id(),
        created_at=NOW,
        until=until,
    )


async def test_an_upload_ban_is_active_until_it_expires(
    uow_factory: UowFactory,
) -> None:
    """LIB-14: `until` in the future bans, in the past does not."""
    user = new_id()
    ban = sanction(SanctionKind.UPLOAD_BAN, user, NOW + HOUR)

    async with uow_factory() as uow:
        await uow.moderation.add_sanction(ban)
        during = await uow.moderation.active_ban(user, NOW)
        after = await uow.moderation.active_ban(user, NOW + 2 * HOUR)

    assert during is not None and during.id == ban.id
    assert during.until == NOW + HOUR
    assert after is None


async def test_a_ban_without_end_date_lasts_until_lifted(
    uow_factory: UowFactory,
) -> None:
    """LIB-14: no `until` means no end."""
    user = new_id()

    async with uow_factory() as uow:
        await uow.moderation.add_sanction(sanction(SanctionKind.UPLOAD_BAN, user))
        ban = await uow.moderation.active_ban(user, NOW + dt.timedelta(days=900))

    assert ban is not None


async def test_a_warning_is_not_a_ban(uow_factory: UowFactory) -> None:
    """LIB-14: warnings are recorded but do not block uploads."""
    user = new_id()

    async with uow_factory() as uow:
        await uow.moderation.add_sanction(sanction(SanctionKind.WARNING, user))
        ban = await uow.moderation.active_ban(user, NOW)

    assert ban is None


async def test_sanctions_list_newest_first_and_filter_by_user(
    uow_factory: UowFactory,
) -> None:
    """LIB-14: the admin list of sanctions, optionally of one user."""
    me, other = new_id(), new_id()
    older = sanction(SanctionKind.WARNING, me)
    newest = Sanction(
        id=new_id(),
        user_id=me,
        kind=SanctionKind.UPLOAD_BAN,
        reason="again",
        set_by=new_id(),
        created_at=NOW + HOUR,
    )
    async with uow_factory() as uow:
        await uow.moderation.add_sanction(older)
        await uow.moderation.add_sanction(newest)
        await uow.moderation.add_sanction(sanction(SanctionKind.WARNING, other))
        mine = await uow.moderation.list_sanctions(me)
        everyone = await uow.moderation.list_sanctions()

    assert [s.id for s in mine] == [newest.id, older.id]
    assert len(everyone) >= 3


# - - - Suggestions - - -


async def test_new_suggestions_are_listed_until_decided(
    uow_factory: UowFactory,
) -> None:
    """LIB-2: a suggestion waits in the queue until a librarian decides."""
    user, handler = new_id(), new_id()
    first = BookSuggestion(
        id=new_id(), user_id=user, title="Atom physics", created_at=NOW, note="Good"
    )
    second = BookSuggestion(
        id=new_id(),
        user_id=user,
        title="Optics",
        created_at=NOW + HOUR,
        url="https://example.org/optics",
    )

    async with uow_factory() as uow:
        await uow.moderation.add_suggestion(second)
        await uow.moderation.add_suggestion(first)
        waiting = await uow.moderation.new_suggestions(limit=10, offset=0)
        first.status = SuggestionStatus.ACCEPTED
        first.handled_by = handler
        await uow.moderation.save_suggestion(first)
        left = await uow.moderation.new_suggestions(limit=10, offset=0)
        loaded = await uow.moderation.get_suggestion(first.id)

    assert [s.title for s in waiting] == ["Atom physics", "Optics"]
    assert [s.title for s in left] == ["Optics"]
    assert loaded is not None
    assert loaded.status is SuggestionStatus.ACCEPTED
    assert loaded.handled_by == handler
    assert waiting[1].url == "https://example.org/optics"


# - - - Queue - - -


async def test_review_queue_lists_pending_materials_oldest_first(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-13: the librarian queue is first in, first out."""
    late = await store_item(pending(30))
    early = await store_item(pending(5))
    await store_item(make_material(status=ItemStatus.PUBLISHED))
    await store_item(make_material(status=ItemStatus.DRAFT))
    await store_item(make_book(status=ItemStatus.PUBLISHED))

    async with uow_factory() as uow:
        page = await uow.moderation.review_queue(limit=10, offset=0)
        second = await uow.moderation.review_queue(limit=1, offset=1)

    assert [e.item_id for e in page] == [early.id, late.id]
    assert page[0].at == NOW + dt.timedelta(minutes=5)
    assert [e.item_id for e in second] == [late.id]


async def test_positions_count_from_one_in_submission_order(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-13: a student sees their place in the queue."""
    first = await store_item(pending(1))
    second = await store_item(pending(2))
    published = await store_item(make_material())

    async with uow_factory() as uow:
        positions = await uow.moderation.pending_positions(
            [second.id, first.id, published.id]
        )

    assert positions == {first.id: 1, second.id: 2}


async def test_queue_age_stats_of_an_empty_queue(uow_factory: UowFactory) -> None:
    """LIB-16: nothing waits, nothing is old."""
    async with uow_factory() as uow:
        stats = await uow.moderation.queue_age_stats(NOW)

    assert stats.length == 0
    assert stats.oldest_age_hours is None
    assert stats.average_hours is None


async def test_queue_age_stats_report_length_oldest_and_average(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-16: the dashboard shows how long the queue has been waiting."""
    await store_item(pending(-60 * 4))  # 4 hours before NOW
    await store_item(pending(-60 * 2))  # 2 hours before NOW

    async with uow_factory() as uow:
        stats = await uow.moderation.queue_age_stats(NOW)

    assert stats.length == 2
    assert stats.oldest_age_hours == pytest.approx(4.0)
    assert stats.average_hours == pytest.approx(3.0)


async def test_report_queue_separates_held_from_reported_items(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: tab Reports = published with open reports, tab Held = held items."""
    reported = await store_item(make_material(title="Reported"))
    held = await store_item(make_material(title="Held", status=ItemStatus.HELD))
    quiet = await store_item(make_material(title="Quiet"))
    async with uow_factory() as uow:
        await uow.moderation.add_report(report(reported, at=NOW + HOUR))
        await uow.moderation.add_report(report(held, at=NOW))
        reports_tab = await uow.moderation.report_queue(held=False, limit=10, offset=0)
        held_tab = await uow.moderation.report_queue(held=True, limit=10, offset=0)

    assert [e.item_id for e in reports_tab] == [reported.id]
    assert reports_tab[0].at == NOW + HOUR
    assert [e.item_id for e in held_tab] == [held.id]
    assert quiet.id not in {e.item_id for e in reports_tab + held_tab}


async def test_a_held_item_without_reports_still_has_a_tab_entry(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-14: a librarian's own hold is listed under its update time."""
    held = make_material(status=ItemStatus.HELD, now=NOW + HOUR)
    await store_item(held)

    async with uow_factory() as uow:
        tab = await uow.moderation.report_queue(held=True, limit=10, offset=0)

    assert [e.item_id for e in tab] == [held.id]
    assert tab[0].at == NOW + HOUR


async def test_rights_candidates_are_live_books_with_open_questions(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-3: live books with unchecked rights or a permission go to the check."""
    permission = await store_item(make_book(title="A", rights=Rights.PERMISSION))
    unchecked = make_book(title="B", status=ItemStatus.HELD)
    assert unchecked.book is not None
    unchecked.book.rights_checked_at = None
    await store_item(unchecked)
    await store_item(make_book(title="Settled"))
    await store_item(
        make_book(title="C", status=ItemStatus.DRAFT, rights=Rights.PERMISSION)
    )
    await store_item(make_material())

    async with uow_factory() as uow:
        ids = await uow.moderation.rights_candidates()

    assert set(ids) == {permission.id, unchecked.id}


# - - - Uploads of one person - - -


async def test_uploads_page_is_newest_first_with_a_status_filter(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-13: `GET /me/library/uploads` lists the person's own materials."""
    me = new_id()
    old = await store_item(
        make_material(title="Old", uploader_id=me, now=NOW - 2 * HOUR)
    )
    new = await store_item(
        make_material(title="New", uploader_id=me, status=ItemStatus.DRAFT, now=NOW)
    )
    await store_item(make_material(title="Somebody else's"))
    await store_item(make_book(title="A book", owner_id=me))

    async with uow_factory() as uow:
        everything = await uow.moderation.uploads_page(
            me, status=None, limit=10, after=None
        )
        drafts = await uow.moderation.uploads_page(
            me, status=ItemStatus.DRAFT, limit=10, after=None
        )

    assert everything == [new.id, old.id]
    assert drafts == [new.id]


async def test_uploads_page_continues_after_a_keyset_position(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-13: the cursor is the (created_at, id) of the last row of the page."""
    me = new_id()
    items = [
        await store_item(
            make_material(title=f"M{i}", uploader_id=me, now=NOW - i * HOUR)
        )
        for i in range(3)
    ]

    async with uow_factory() as uow:
        first = await uow.moderation.uploads_page(me, status=None, limit=2, after=None)
        rest = await uow.moderation.uploads_page(
            me,
            status=None,
            limit=2,
            after=(items[1].created_at, items[1].id),
        )

    assert first == [items[0].id, items[1].id]
    assert rest == [items[2].id]


async def test_upload_times_count_submissions_in_the_window(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-13: limits count submissions, not drafts, and can skip one item."""
    me = new_id()
    old = await store_item(pending(-60 * 30, me))  # 30 hours before NOW
    recent = await store_item(pending(-60, me))
    await store_item(draft(me))
    await store_item(pending(-30))  # somebody else
    since = NOW - dt.timedelta(hours=24)
    later = make_material(status=ItemStatus.CHANGES_REQUESTED, uploader_id=me, now=NOW)
    assert later.material is not None
    later.material.submitted_at = NOW
    await store_item(later)

    async with uow_factory() as uow:
        times = await uow.moderation.upload_times(me, since)
        skipping = await uow.moderation.upload_times(me, since, exclude=later.id)
        count = await uow.moderation.count_uploads(me, since)
        wide = await uow.moderation.count_uploads(me, NOW - dt.timedelta(days=7))

    assert sorted(times) == [recent.created_at, NOW]
    assert skipping == [recent.created_at]
    assert count == 2
    assert wide == 3
    assert old.created_at < since


# - - - Versions, owner items, drafts, purge - - -


async def test_open_versions_are_unfinished_successors(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-13: one new version at a time per published material."""
    base = await store_item(make_material())
    successor = make_material(
        title="v2", status=ItemStatus.DRAFT, supersedes_id=base.id
    )
    done = make_material(title="v1b", status=ItemStatus.REJECTED, supersedes_id=base.id)
    await store_item(successor)
    await store_item(done)

    async with uow_factory() as uow:
        open_ones = await uow.moderation.open_versions(base.id)

    assert open_ones == [successor.id]


async def test_owner_item_ids_filter_by_status(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-13: account closure finds the person's unfinished materials."""
    me = new_id()
    unsent = await store_item(draft(me))
    queued = await store_item(pending(1, me))
    await store_item(make_material(uploader_id=me))

    async with uow_factory() as uow:
        ids = await uow.moderation.owner_item_ids(
            me,
            [ItemStatus.DRAFT, ItemStatus.PENDING_REVIEW, ItemStatus.CHANGES_REQUESTED],
        )

    assert set(ids) == {unsent.id, queued.id}


async def test_deleting_a_draft_removes_it_with_details_and_files(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-13: a withdrawn draft disappears; anything submitted stays."""
    unsent = await store_item(draft())
    live = await store_item(make_material(title="Live"))

    async with uow_factory() as uow:
        await uow.moderation.delete_draft(unsent.id)
        await uow.moderation.delete_draft(live.id)
        gone = await uow.items.get(unsent.id)
        kept = await uow.items.get(live.id)

    assert gone is None
    assert kept is not None


async def test_purgeable_items_are_old_rejected_or_unpublished_with_files(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-13: rejected after 30 days and unpublished after 90 still holding files."""
    day = dt.timedelta(days=1)
    old_rejected = await store_item(
        make_material(title="r1", status=ItemStatus.REJECTED, now=NOW - 31 * day)
    )
    await store_item(
        make_material(title="r2", status=ItemStatus.REJECTED, now=NOW - 29 * day)
    )
    old_unpublished = await store_item(
        make_material(title="u1", status=ItemStatus.UNPUBLISHED, now=NOW - 91 * day)
    )
    await store_item(
        make_material(title="u2", status=ItemStatus.UNPUBLISHED, now=NOW - 31 * day)
    )
    no_files = make_material(
        title="u3", status=ItemStatus.UNPUBLISHED, now=NOW - 99 * day
    )
    no_files.files = []
    await store_item(no_files)
    await store_item(
        make_material(title="p", status=ItemStatus.PUBLISHED, now=NOW - 99 * day)
    )

    async with uow_factory() as uow:
        ids = await uow.moderation.purgeable_items(
            rejected_before=NOW - 30 * day,
            unpublished_before=NOW - 90 * day,
            limit=50,
        )

    assert set(ids) == {old_rejected.id, old_unpublished.id}
