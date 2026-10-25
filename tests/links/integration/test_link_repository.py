"""SQL repository and unit of work of links against PostgreSQL (SL-2, SL-7, SL-9)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.modules.links.domain.errors import SlugTakenError
from app.modules.links.domain.link import LessonRole, Link, LinkKind, ShareMode
from app.modules.links.infrastructure.repositories.link_repository import (
    SqlLinkRepository,
)
from app.modules.links.infrastructure.uow import LinksSqlUnitOfWork
from app.modules.links.ports.link_repository import ModerationCursor
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def make_link(slug: str, owner: UUID | None = None, **changes: object) -> Link:
    """A URL link with defaults; keyword arguments override fields."""
    link = Link(
        id=new_id(),
        slug=slug,
        kind=LinkKind.URL,
        owner_id=owner or new_id(),
        created_at=NOW,
        target_url="https://example.org/",
    )
    for key, value in changes.items():
        setattr(link, key, value)
    return link


@pytest_asyncio.fixture
async def repo(db_session: AsyncSession) -> AsyncIterator[SqlLinkRepository]:
    """A repository on the rolled-back test transaction."""
    await db_session.execute(text("DELETE FROM links.links"))
    yield SqlLinkRepository(db_session)


async def test_add_and_get_round_trip_every_field(repo: SqlLinkRepository) -> None:
    """Link model: all fields survive a save."""
    lesson, file_id, target = new_id(), new_id(), new_id()
    original = make_link(
        "7_k",
        kind=LinkKind.FILE,
        target_url=None,
        file_id=file_id,
        title="Lecture",
        lesson_id=lesson,
        lesson_role=LessonRole.MATERIAL,
        hits=3,
    )
    share = make_link(
        "c-1",
        kind=LinkKind.CHAT,
        target_url=None,
        target_id=target,
        share_mode=ShareMode.SNAPSHOT,
        snapshot_seq=4,
        expires_at=NOW + timedelta(days=1),
    )

    await repo.add(original)
    await repo.add(share)

    assert await repo.get(original.id) == original
    assert await repo.get(share.id) == share
    assert await repo.get(new_id()) is None


async def test_slug_lookup_is_case_sensitive(repo: SqlLinkRepository) -> None:
    """Link model: slugs are case-sensitive."""
    lower, upper = make_link("abc"), make_link("ABC")
    await repo.add(lower)
    await repo.add(upper)

    assert (await repo.get_by_slug("abc")) == lower
    assert (await repo.get_by_slug("ABC")) == upper
    assert await repo.get_by_slug("aBc") is None


async def test_duplicate_slug_raises_and_keeps_the_transaction_usable(
    repo: SqlLinkRepository,
) -> None:
    """SL-2: unique (slug) where slug_released_at is null; callers retry."""
    await repo.add(make_link("dup"))

    with pytest.raises(SlugTakenError):
        await repo.add(make_link("dup"))
    other = make_link("free")
    await repo.add(other)

    assert await repo.get(other.id) == other


async def test_a_released_slug_can_be_used_again(repo: SqlLinkRepository) -> None:
    """SL-7: the partial unique index frees released slugs."""
    old = make_link("again", revoked_at=NOW, slug_released_at=NOW)
    await repo.add(old)
    fresh = make_link("again")

    await repo.add(fresh)

    assert await repo.get_by_slug("again") == fresh
    assert await repo.get(old.id) == old


async def test_check_constraints_reject_inconsistent_links(
    repo: SqlLinkRepository,
) -> None:
    """Link model checks: kind and target must agree; lesson only on url and file."""
    with pytest.raises(IntegrityError):
        await repo.add(make_link("bad1", target_url=None))


async def test_save_updates_the_row(repo: SqlLinkRepository) -> None:
    """Repositories write entities back."""
    link = make_link("save")
    await repo.add(link)
    link.revoke(NOW)
    link.register_report(NOW)

    await repo.save(link)

    stored = await repo.get(link.id)
    assert stored is not None
    assert stored.revoked_at == NOW
    assert stored.reports == 1


async def test_owner_list_is_newest_first_with_cursor_and_filters(
    repo: SqlLinkRepository,
) -> None:
    """SL-7: own links, deleted short links hidden, revoked shares kept."""
    owner, other = new_id(), new_id()
    chat_id = new_id()
    links = [make_link(f"l{i}", owner) for i in range(4)]
    for link in links:
        await repo.add(link)
    deleted = make_link("deleted", owner, revoked_at=NOW)
    revoked_share = make_link(
        "c-r",
        owner,
        kind=LinkKind.CHAT,
        target_url=None,
        target_id=chat_id,
        share_mode=ShareMode.LIVE,
        revoked_at=NOW,
    )
    foreign = make_link("foreign", other)
    for link in (deleted, revoked_share, foreign):
        await repo.add(link)

    page = await repo.list_by_owner(
        owner, kind=None, target_id=None, before_id=None, limit=3
    )
    rest = await repo.list_by_owner(
        owner, kind=None, target_id=None, before_id=page[-1].id, limit=10
    )
    chats = await repo.list_by_owner(
        owner, kind=LinkKind.CHAT, target_id=chat_id, before_id=None, limit=10
    )

    ids = [x.id for x in page + rest]
    assert ids == sorted(ids, reverse=True)
    assert set(ids) == {*(x.id for x in links), revoked_share.id}
    assert deleted.id not in ids and foreign.id not in ids
    assert [x.id for x in chats] == [revoked_share.id]


async def test_lesson_resources_exclude_revoked_and_other_lessons(
    repo: SqlLinkRepository,
) -> None:
    """ACA-9: live resources of the lessons, oldest first."""
    lesson, other_lesson = new_id(), new_id()
    first = make_link("r1", lesson_id=lesson, lesson_role=LessonRole.MATERIAL)
    second = make_link(
        "r2",
        lesson_id=lesson,
        lesson_role=LessonRole.ATTACHMENT,
        created_at=NOW + timedelta(minutes=1),
    )
    gone = make_link(
        "r3", lesson_id=lesson, lesson_role=LessonRole.ATTACHMENT, revoked_at=NOW
    )
    elsewhere = make_link("r4", lesson_id=other_lesson, lesson_role=LessonRole.MATERIAL)
    plain = make_link("r5")
    for link in (second, first, gone, elsewhere, plain):
        await repo.add(link)

    found = await repo.list_for_lessons([lesson])

    assert [x.id for x in found] == [first.id, second.id]
    assert await repo.list_for_lessons([]) == []


async def test_moderation_queue_order_cursor_and_review(
    repo: SqlLinkRepository,
) -> None:
    """SL-9, UF-ADM-10: reports desc, last report desc, reviewed ones leave."""
    quiet = make_link("q", reports=1, last_reported_at=NOW)
    busy = make_link("b", reports=3, last_reported_at=NOW - timedelta(days=1))
    recent = make_link("n", reports=1, last_reported_at=NOW + timedelta(hours=1))
    dismissed = make_link(
        "d",
        reports=9,
        last_reported_at=NOW,
        reports_reviewed_at=NOW + timedelta(minutes=1),
    )
    reopened = make_link(
        "o",
        reports=2,
        last_reported_at=NOW + timedelta(hours=2),
        reports_reviewed_at=NOW,
    )
    clean = make_link("c")
    for link in (quiet, busy, recent, dismissed, reopened, clean):
        await repo.add(link)

    everything = await repo.moderation_queue(after=None, limit=10)
    first = await repo.moderation_queue(after=None, limit=2)
    last = first[-1]
    assert last.last_reported_at is not None
    rest = await repo.moderation_queue(
        after=ModerationCursor(last.reports, last.last_reported_at, last.id), limit=10
    )

    expected = [busy.id, reopened.id, recent.id, quiet.id]
    assert [x.id for x in everything] == expected
    assert [x.id for x in first + rest] == expected


async def test_owner_search_and_active_listing(repo: SqlLinkRepository) -> None:
    """ADM-13, ID-28: links by owners; active = not revoked."""
    ann, bob = new_id(), new_id()
    live, dead = make_link("a1", ann), make_link("a2", ann, revoked_at=NOW)
    theirs = make_link("b1", bob)
    for link in (live, dead, theirs):
        await repo.add(link)

    by_owners = await repo.list_by_owners([ann, bob], 10)
    active = await repo.active_by_owner(ann)

    assert {x.id for x in by_owners} == {live.id, dead.id, theirs.id}
    assert [x.id for x in active] == [live.id]
    assert await repo.list_by_owners([], 10) == []


async def test_release_and_hits(repo: SqlLinkRepository) -> None:
    """SL-6, SL-7: counters add up; only links revoked before the cutoff are freed."""
    old = make_link("old", revoked_at=NOW - timedelta(days=100))
    fresh = make_link("fresh", revoked_at=NOW - timedelta(days=10))
    live = make_link("live", hits=5)
    for link in (old, fresh, live):
        await repo.add(link)

    released = await repo.release_revoked_before(NOW - timedelta(days=90), NOW)
    await repo.add_hits({live.id: 2, old.id: 1}, NOW)

    assert released == 1
    stored_old, stored_live = await repo.get(old.id), await repo.get(live.id)
    assert stored_old is not None and stored_old.slug_released_at == NOW
    assert stored_live is not None
    assert (stored_live.hits, stored_live.last_hit_at) == (7, NOW)
    fresh_stored = await repo.get(fresh.id)
    assert fresh_stored is not None and fresh_stored.slug_released_at is None


async def test_unit_of_work_commits_and_rolls_back(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    """The SQL unit of work gives each use case its own transaction."""
    await db_session.execute(text("DELETE FROM links.links"))
    link = make_link("uow")

    def uow() -> LinksSqlUnitOfWork:
        return LinksSqlUnitOfWork(
            sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer, None
        )

    async with uow() as tx:
        await tx.links.add(link)
        await tx.commit()
    with pytest.raises(RuntimeError):
        async with uow() as tx:
            await tx.links.add(make_link("rolled-back"))
            raise RuntimeError("boom")

    async with uow() as tx:
        assert await tx.links.get(link.id) == link
        assert await tx.links.get_by_slug("rolled-back") is None


async def test_hide_rules_and_hidden_by_rule_round_trip(
    repo: SqlLinkRepository,
) -> None:
    """The "hide EMIS sources" rule is idempotent; hidden_by_rule survives a save."""
    teacher, subject, group = new_id(), new_id(), new_id()
    await repo.set_hide_rule(teacher, subject, group, on=True, now=NOW)
    await repo.set_hide_rule(teacher, subject, group, on=True, now=NOW)
    assert await repo.hide_rules([teacher]) == {(teacher, subject, group)}
    link = make_link(
        "rule01",
        lesson_id=new_id(),
        lesson_role=LessonRole.MATERIAL,
    )
    link.hide(teacher, NOW, by_rule=True)
    await repo.add(link)
    stored = await repo.get(link.id)
    assert stored is not None and stored.hidden_by_rule
    await repo.set_hide_rule(teacher, subject, group, on=False, now=NOW)
    assert await repo.hide_rules([teacher]) == set()
