"""SL-6, SL-7: hit flushing and slug release tasks."""

from datetime import timedelta

from app.modules.links.domain.errors import SlugTakenError
from app.modules.links.domain.link import Link, LinkKind
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.links.world import LinksWorld

import pytest


async def _link(world: LinksWorld, path: str = "a") -> Link:
    ann = world.people.get("Ann") or world.person("Ann")
    view = await world.services.create_link.execute(
        ann, kind=LinkKind.URL, target_url=f"https://en.wikipedia.org/wiki/{path}"
    )
    return view.link


async def test_flush_moves_redis_counters_into_the_database(
    world: LinksWorld, clock: FixedClock
) -> None:
    """SL-6: clicks are flushed every five minutes."""
    first, second = await _link(world, "a"), await _link(world, "b")
    for _ in range(3):
        await world.services.open_short_link.execute(
            first.slug, ip="203.0.113.7", accept_language=None
        )
    await world.services.open_short_link.execute(
        second.slug, ip="203.0.113.7", accept_language=None
    )

    flushed = await world.services.flush_hits.execute()

    stored = world.uow.store.links
    assert flushed == 2
    assert (stored[first.id].hits, stored[second.id].hits) == (3, 1)
    assert stored[first.id].last_hit_at == clock.now()
    assert [k async for k in world.redis.scan_iter(match="links:hits:*")] == []


async def test_flush_adds_to_existing_hits_and_ignores_empty_runs(
    world: LinksWorld,
) -> None:
    """SL-6: counters accumulate across flushes."""
    link = await _link(world)
    assert await world.services.flush_hits.execute() == 0

    for _ in range(2):
        await world.services.open_short_link.execute(
            link.slug, ip="203.0.113.7", accept_language=None
        )
        await world.services.flush_hits.execute()

    assert world.uow.store.links[link.id].hits == 2


async def test_a_failed_flush_keeps_the_counters(world: LinksWorld) -> None:
    """SL-6: no clicks are lost when the database is unavailable."""
    link = await _link(world)
    await world.services.open_short_link.execute(
        link.slug, ip="203.0.113.7", accept_language=None
    )

    def broken() -> object:
        raise ConnectionError("db down")

    original = world.services.flush_hits.uow_factory
    world.services.flush_hits.uow_factory = broken  # type: ignore[assignment]
    try:
        try:
            await world.services.flush_hits.execute()
        except ConnectionError:
            pass
    finally:
        world.services.flush_hits.uow_factory = original

    assert await world.redis.get(f"links:hits:{link.id}") == "1"
    assert await world.services.flush_hits.execute() == 1


async def test_slugs_are_released_ninety_days_after_revocation(
    world: LinksWorld, clock: FixedClock
) -> None:
    """SL-7: IDs of deleted links are free again after 90 days."""
    ann = world.person("Ann")
    link = await _link(world)
    await world.services.delete_link.execute(ann, link.id)

    clock.advance(days=89)
    assert await world.services.release_slugs.execute() == 0
    clock.advance(days=2)
    released = await world.services.release_slugs.execute()
    again = await world.services.release_slugs.execute()

    stored = world.uow.store.links[link.id]
    assert released == 1
    assert again == 0
    assert stored.slug_released_at == clock.now()
    assert stored.revoked_at is not None
    assert clock.now() - stored.revoked_at > timedelta(days=90)


async def test_a_released_slug_can_be_given_to_a_new_link(
    world: LinksWorld, clock: FixedClock
) -> None:
    """SL-7: the row stays as evidence, the slug becomes free."""
    ann = world.person("Ann")
    link = await _link(world)
    await world.services.delete_link.execute(ann, link.id)
    fresh = Link(
        id=new_id(),
        slug=link.slug,
        kind=LinkKind.URL,
        owner_id=ann.user_id,
        created_at=clock.now(),
        target_url="https://example.org/",
    )
    async with world.uow() as uow:
        with pytest.raises(SlugTakenError):
            await uow.links.add(fresh)

    clock.advance(days=91)
    await world.services.release_slugs.execute()
    async with world.uow() as uow:
        await uow.links.add(fresh)
        await uow.commit()

    assert world.uow.store.links[fresh.id].slug == link.slug
    assert world.uow.store.links[link.id].slug == link.slug
