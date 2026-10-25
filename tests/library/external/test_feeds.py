"""LIB-12: feeds are stored and toggled; the sync that would run them is not built."""

from app.modules.library.domain.enums import ExternalAccess
from app.modules.library.domain.external_errors import (
    ExternalSyncUnavailableError,
    FeedNotFoundError,
)
from app.modules.library.domain.external_feed import Feed, FeedAction, FeedParams
from app.modules.library.ports.unit_of_work import UowFactory
from app.modules.library.wiring_external import ExternalServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.library.external_catalog import FakeExternalCatalog

import pytest

PARAMS = FeedParams(
    category=1,
    field_ids=[27],
    type_ids=[9, 2],
    language_ids=[2, 3, 26],
    access=[ExternalAccess.OPEN, ExternalAccess.PARTIAL],
)


async def make_feed(external: ExternalServices, admin: Actor) -> Feed:
    """Create a feed through the use case."""
    return await external.create_feed.execute(
        admin, name="Physics textbooks", params=PARAMS, max_items=500
    )


async def test_a_new_feed_is_off_with_no_estimate_and_no_runs(
    external: ExternalServices, admin: Actor, clock: FixedClock
) -> None:
    """LIB-12: created disabled; nothing ran."""
    feed = await make_feed(external, admin)

    assert feed.name == "Physics textbooks"
    assert feed.params == PARAMS
    assert feed.max_items == 500
    assert feed.enabled is False
    assert feed.estimate is None
    assert (feed.last_run_at, feed.last_status, feed.last_count) == (None, None, None)
    assert feed.created_at == clock.now()


async def test_feeds_are_listed(external: ExternalServices, admin: Actor) -> None:
    """LIB-12: `GET /feeds`."""
    created = await make_feed(external, admin)

    feeds = await external.list_feeds.execute(admin)

    assert [f.id for f in feeds] == [created.id]


async def test_update_changes_only_what_is_sent(
    external: ExternalServices, admin: Actor
) -> None:
    """LIB-12: PATCH is partial."""
    feed = await make_feed(external, admin)

    updated = await external.update_feed.execute(admin, feed.id, name="Physics")

    assert updated.name == "Physics"
    assert updated.params == PARAMS
    assert updated.max_items == 500


async def test_new_params_drop_the_old_estimate(
    external: ExternalServices, admin: Actor, uow_factory: UowFactory
) -> None:
    """LIB-12: the estimate was for other filters."""
    feed = await make_feed(external, admin)
    async with uow_factory() as uow:
        stored = await uow.external.get_feed(feed.id)
        assert stored is not None
        stored.estimate = 411
        await uow.external.save_feed(stored)
        await uow.commit()

    same = await external.update_feed.execute(admin, feed.id, max_items=100)
    changed = await external.update_feed.execute(
        admin, feed.id, params=FeedParams(field_ids=[25])
    )

    assert same.estimate == 411
    assert changed.estimate is None
    assert changed.params.field_ids == [25]


async def test_a_missing_feed_is_not_found(
    external: ExternalServices, admin: Actor
) -> None:
    """LIB-12: update, delete and actions on an unknown id."""
    with pytest.raises(FeedNotFoundError):
        await external.update_feed.execute(admin, new_id(), name="x")
    with pytest.raises(FeedNotFoundError):
        await external.delete_feed.execute(admin, new_id())
    with pytest.raises(FeedNotFoundError):
        await external.run_feed_action.execute(admin, new_id(), FeedAction.ENABLE)


async def test_delete_removes_the_feed(
    external: ExternalServices, admin: Actor
) -> None:
    """LIB-12: `DELETE /feeds/{id}`."""
    feed = await make_feed(external, admin)

    await external.delete_feed.execute(admin, feed.id)

    assert await external.list_feeds.execute(admin) == []


async def test_enable_and_disable_toggle_the_flag(
    external: ExternalServices, admin: Actor
) -> None:
    """LIB-12: the only actions that work without the sync."""
    feed = await make_feed(external, admin)

    enabled = await external.run_feed_action.execute(admin, feed.id, FeedAction.ENABLE)
    disabled = await external.run_feed_action.execute(
        admin, feed.id, FeedAction.DISABLE
    )

    assert enabled.enabled is True
    assert disabled.enabled is False


@pytest.mark.parametrize("action", [FeedAction.DRY_RUN, FeedAction.RUN])
async def test_dry_run_and_run_say_the_sync_is_not_built(
    external: ExternalServices,
    catalog: FakeExternalCatalog,
    admin: Actor,
    action: FeedAction,
) -> None:
    """LIB-12: `409 library/external-sync-unavailable`; UniLibrary is not called."""
    feed = await make_feed(external, admin)

    with pytest.raises(ExternalSyncUnavailableError) as caught:
        await external.run_feed_action.execute(admin, feed.id, action)

    assert caught.value.status == 409
    assert caught.value.code == "library/external-sync-unavailable"
    assert catalog.calls == 0


async def test_feeds_work_while_the_integration_is_off(
    external_off: ExternalServices, admin: Actor
) -> None:
    """LIB-12: Administration prepares feeds before switching on."""
    feed = await external_off.create_feed.execute(
        admin, name="Prepared", params=FeedParams(), max_items=10
    )

    assert feed.params == FeedParams()


async def test_only_administration_manages_feeds(
    external: ExternalServices, admin: Actor, student: Actor, librarian: Actor
) -> None:
    """LIB-12: students and librarians are refused."""
    feed = await make_feed(external, admin)

    for actor in (student, librarian):
        with pytest.raises(ForbiddenError):
            await external.list_feeds.execute(actor)
        with pytest.raises(ForbiddenError):
            await external.create_feed.execute(
                actor, name="x", params=PARAMS, max_items=1
            )
        with pytest.raises(ForbiddenError):
            await external.update_feed.execute(actor, feed.id, name="x")
        with pytest.raises(ForbiddenError):
            await external.delete_feed.execute(actor, feed.id)
        with pytest.raises(ForbiddenError):
            await external.run_feed_action.execute(actor, feed.id, FeedAction.ENABLE)
