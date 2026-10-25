"""LIB-6: the SQL progress keeps one row per user and item."""

import datetime as dt
from uuid import UUID

from app.modules.library.domain.reader_progress import ReadingProgress
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.ids import new_id

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def progress(
    user_id: UUID,
    item_id: UUID | None = None,
    *,
    percent: float = 10,
    minutes: int = 0,
    page: int = 1,
    seconds: int = 30,
) -> ReadingProgress:
    """Progress opened `minutes` after NOW."""
    at = NOW + dt.timedelta(minutes=minutes)
    return ReadingProgress(
        user_id=user_id,
        item_id=item_id or new_id(),
        file_id=new_id(),
        locator={"page": page},
        percent=percent,
        opened_at=at,
        seconds_read=seconds,
        client_ts=at,
    )


async def test_save_inserts_then_updates_the_same_row(uow_factory: UowFactory) -> None:
    """LIB-6: a second save moves the position and keeps one row."""
    user, item = new_id(), new_id()
    async with uow_factory() as uow:
        await uow.progress.save(progress(user, item, page=2, percent=5))
        await uow.progress.save(
            progress(user, item, page=9, percent=40, minutes=3, seconds=75)
        )

        loaded = await uow.progress.get(user, item)
        percents = await uow.progress.percents(user, [item])

    assert loaded is not None
    assert loaded.locator == {"page": 9}
    assert loaded.percent == 40
    assert loaded.seconds_read == 75
    assert loaded.opened_at == NOW + dt.timedelta(minutes=3)
    assert percents == {item: 40.0}


async def test_get_is_scoped_to_the_user(uow_factory: UowFactory) -> None:
    """LIB-16: another user's progress is never returned."""
    user, stranger, item = new_id(), new_id(), new_id()
    async with uow_factory() as uow:
        await uow.progress.save(progress(user, item))

        assert await uow.progress.get(stranger, item) is None


async def test_unfinished_lists_recent_first_and_skips_finished(
    uow_factory: UowFactory,
) -> None:
    """LIB-8: continue reading shows what is not at 100 percent, newest first."""
    user = new_id()
    old = progress(user, minutes=1)
    done = progress(user, percent=100, minutes=2)
    recent = progress(user, minutes=3)
    async with uow_factory() as uow:
        for saved in (old, done, recent):
            await uow.progress.save(saved)

        rows = await uow.progress.unfinished(user, limit=10)
        paged = await uow.progress.unfinished(user, limit=1, offset=1)

    assert [r.item_id for r in rows] == [recent.item_id, old.item_id]
    assert [r.item_id for r in paged] == [old.item_id]


async def test_delete_all_removes_only_that_users_progress(
    uow_factory: UowFactory,
) -> None:
    """LIB-16: closing an account removes the progress."""
    leaving, staying = new_id(), new_id()
    async with uow_factory() as uow:
        await uow.progress.save(progress(leaving))
        await uow.progress.save(progress(staying))

        assert await uow.progress.delete_all(leaving) == 1
        assert await uow.progress.unfinished(leaving, limit=5) == []
        assert len(await uow.progress.unfinished(staying, limit=5)) == 1
