"""LIB-13, LIB-14: queue reminders, rights review, purge and account closure."""

import datetime as dt
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemStatus, Rights
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from app.shared.notifications import NotificationDraft, NotificationType
from tests.factories.library import make_book, make_material
from tests.fakes.clock import FixedClock
from tests.fakes.library.material_files import MaterialFilesApi

MakePending = Callable[..., Awaitable[UUID]]
MakeDraft = Callable[..., Awaitable[UUID]]
SetStatus = Callable[..., Awaitable[None]]
StoreItem = Callable[[Item], Awaitable[Item]]
LoadItem = Callable[[UUID | None], Awaitable[Item]]

DAY = dt.timedelta(days=1)


# - - - remind_queue - - -


async def test_nothing_is_sent_while_the_queue_is_fresh(
    library: LibraryServices,
    student: Actor,
    make_pending: MakePending,
    clock: FixedClock,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-13: two school days is the service level; one day is fine."""
    await make_pending(student)
    clock.advance(days=1)
    outbox.clear()

    sent = await library.materials.remind_queue.execute()

    assert sent == 0
    assert outbox == []


async def test_librarians_and_admins_are_reminded_of_items_waiting_too_long(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    librarian: Actor,
    other_librarian: Actor,
    admin: Actor,
    make_pending: MakePending,
    clock: FixedClock,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-13: one reminder per librarian with the count and the oldest wait."""
    await make_pending(student)
    clock.advance(days=2)
    await make_pending(other_student, title="Newer")
    clock.advance(days=1)  # the first waited 3 days, the second 1
    outbox.clear()

    sent = await library.materials.remind_queue.execute()

    assert sent == 3
    assert {n.user_id for n in outbox} == {
        librarian.user_id,
        other_librarian.user_id,
        admin.user_id,
    }
    assert all(n.type is NotificationType.LIBRARY_QUEUE_WAITING for n in outbox)
    assert outbox[0].payload == {"count": 1, "oldest_hours": 72}
    assert all(n.dedupe_key.endswith(":2026-10-09") for n in outbox)
    assert len({n.dedupe_key for n in outbox}) == 3


async def test_a_rerun_the_same_day_uses_the_same_keys(
    library: LibraryServices,
    student: Actor,
    make_pending: MakePending,
    clock: FixedClock,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-13: the outbox deduplicates by key, so a rerun adds nothing."""
    await make_pending(student)
    clock.advance(days=3)
    await library.materials.remind_queue.execute()
    first = {n.dedupe_key for n in outbox}
    outbox.clear()

    await library.materials.remind_queue.execute()
    clock.advance(days=1)
    await library.materials.remind_queue.execute()

    keys = [n.dedupe_key for n in outbox]
    assert first <= set(keys)
    assert len(set(keys)) > len(first)


async def test_sundays_do_not_count_towards_the_wait(
    library: LibraryServices,
    student: Actor,
    make_pending: MakePending,
    clock: FixedClock,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-13: submitted Friday, checked on Monday at the same hour: 48 school hours."""
    clock.set(dt.datetime(2026, 10, 2, 9, 0, tzinfo=dt.UTC))
    await make_pending(student)
    clock.set(dt.datetime(2026, 10, 5, 9, 0, tzinfo=dt.UTC))
    outbox.clear()

    assert await library.materials.remind_queue.execute() == 0
    clock.advance(hours=1)
    assert await library.materials.remind_queue.execute() > 0


# - - - rights_review - - -


async def test_librarians_hear_once_about_permissions_ending_soon(
    library: LibraryServices,
    librarian: Actor,
    other_librarian: Actor,
    admin: Actor,
    store_item: StoreItem,
    outbox: list[NotificationDraft],
) -> None:
    """LIB-3: permissions ending within 60 days; others are ignored."""
    for title, expires in (("Soon", "2026-11-01"), ("Later", "2027-05-01")):
        book = make_book(title=title, rights=Rights.PERMISSION)
        assert book.book is not None
        book.book.rights_basis = {"permission_expires_on": expires}
        await store_item(book)
    unchecked = make_book(title="Unchecked")
    assert unchecked.book is not None
    unchecked.book.rights_checked_at = None
    await store_item(unchecked)
    outbox.clear()

    sent = await library.materials.review_rights.execute()

    assert sent == 3
    assert {n.user_id for n in outbox} == {
        librarian.user_id,
        other_librarian.user_id,
        admin.user_id,
    }
    assert outbox[0].type is NotificationType.LIBRARY_QUEUE_WAITING
    assert outbox[0].payload == {"count": 1, "oldest_hours": 0, "kind": "rights"}
    assert all(":rights:2026-10-06" in n.dedupe_key for n in outbox)


async def test_no_expiring_permission_means_no_message(
    library: LibraryServices, store_item: StoreItem, outbox: list[NotificationDraft]
) -> None:
    """LIB-3: silence when everything is in order."""
    await store_item(make_book())
    outbox.clear()

    assert await library.materials.review_rights.execute() == 0
    assert outbox == []


# - - - purge - - -


async def test_old_rejected_and_unpublished_materials_lose_their_files(
    library: LibraryServices,
    store_item: StoreItem,
    load_item: LoadItem,
    files_api: MaterialFilesApi,
    clock: FixedClock,
    uow_factory: UowFactory,
) -> None:
    """LIB-13: rejected after 30 days, unpublished after 90; the item row stays."""
    now = clock.now()
    rejected = await store_item(
        make_material(title="r", status=ItemStatus.REJECTED, now=now - 31 * DAY)
    )
    unpublished = await store_item(
        make_material(title="u", status=ItemStatus.UNPUBLISHED, now=now - 91 * DAY)
    )
    fresh = await store_item(
        make_material(title="f", status=ItemStatus.REJECTED, now=now - 5 * DAY)
    )
    published = await store_item(make_material(title="p", now=now - 200 * DAY))
    doomed = [rejected.files[0].file_id, unpublished.files[0].file_id]

    purged = await library.materials.purge_files.execute()

    assert purged == 2
    assert set(files_api.deleted) == set(doomed)
    for item in (rejected, unpublished):
        stored = await load_item(item.id)
        assert stored.files == []
        assert stored.has_text is False
    assert (await load_item(fresh.id)).files
    assert (await load_item(published.id)).files
    assert await library.materials.purge_files.execute() == 0


# - - - delete_owner - - -


async def test_closing_an_account_withdraws_unfinished_materials_only(
    library: LibraryServices,
    student: Actor,
    other_student: Actor,
    make_draft: MakeDraft,
    make_pending: MakePending,
    set_status: SetStatus,
    load_item: LoadItem,
    files_api: MaterialFilesApi,
    uow_factory: UowFactory,
) -> None:
    """LIB-13: drafts go, queued ones are withdrawn, published ones stay."""
    draft = await make_draft(student, title="Draft")
    draft_file = (await load_item(draft)).files[0].file_id
    queued = await make_pending(student, title="Queued")
    sent_back = await make_pending(student, title="Sent back")
    await set_status(sent_back, ItemStatus.CHANGES_REQUESTED)
    live = await make_pending(student, title="Live")
    await set_status(live, ItemStatus.PUBLISHED)
    other = await make_pending(other_student, title="Other")

    changed = await library.materials.delete_owner.execute(student.user_id)

    assert changed == 3
    async with uow_factory() as uow:
        assert await uow.items.get(draft) is None
    assert draft_file in files_api.deleted
    for item_id in (queued, sent_back):
        item = await load_item(item_id)
        assert (item.status, item.status_reason) == (
            ItemStatus.UNPUBLISHED,
            "account_closed",
        )
    assert (await load_item(live)).status is ItemStatus.PUBLISHED
    assert (await load_item(other)).status is ItemStatus.PENDING_REVIEW
