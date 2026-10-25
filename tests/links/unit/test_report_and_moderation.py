"""SL-9, SL-8, ADM-13, UF-PUB-05, UF-ADM-10: reports and moderation."""

from datetime import date

from app.modules.links.domain.errors import LinkNotFoundError
from app.modules.links.domain.link import LessonRole, Link, LinkKind
from app.modules.links.domain.report_reason import ReportReason
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError, RateLimitedError
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.links.world import LinksWorld

import pytest

IP = "203.0.113.7"


async def _link(world: LinksWorld, owner: Actor, path: str = "a") -> Link:
    return (
        await world.services.create_link.execute(
            owner, kind=LinkKind.URL, target_url=f"https://example.org/{path}"
        )
    ).link


async def _report(world: LinksWorld, slug: str, ip: str = IP) -> None:
    await world.services.report_link.execute(
        slug, ReportReason.PHISHING, "looks fake", ip=ip
    )


async def test_report_counts_and_is_audited(
    world: LinksWorld, clock: FixedClock
) -> None:
    """SL-9: the counter goes up and the time is recorded."""
    link = await _link(world, world.person("Ann"))

    await _report(world, link.slug)

    stored = world.uow.store.links[link.id]
    assert stored.reports == 1
    assert stored.last_reported_at == clock.now()
    audit = world.uow.store.audits[-1]
    assert audit.type == "link.reported"
    assert audit.metadata is not None
    assert audit.metadata["reason"] == "phishing"
    assert audit.metadata["slug"] == link.slug


async def test_report_accepts_a_full_url_and_share_slugs(world: LinksWorld) -> None:
    """UF-PUB-05: reports come from short links, interstitials and shares."""
    ann = world.person("Ann")
    link = await _link(world, ann)
    chat = world.ai.add_chat(ann.user_id, [("user", "a")])
    share = (
        await world.services.create_share.execute(
            ann, kind=LinkKind.CHAT, target_id=chat
        )
    ).link

    await _report(world, f"https://s.ihsu.uz/{link.slug}")
    await _report(world, share.slug)

    assert world.uow.store.links[link.id].reports == 1
    assert world.uow.store.links[share.id].reports == 1


async def test_report_of_an_unknown_slug_is_a_404(world: LinksWorld) -> None:
    """UF-PUB-05: there is nothing to report."""
    with pytest.raises(LinkNotFoundError):
        await _report(world, "nope")


async def test_eleventh_report_from_one_ip_in_an_hour_is_rate_limited(
    world: LinksWorld,
) -> None:
    """UF-PUB-05 1a: many reports from one IP."""
    link = await _link(world, world.person("Ann"))
    for _ in range(10):
        await _report(world, link.slug)

    with pytest.raises(RateLimitedError):
        await _report(world, link.slug)
    await _report(world, link.slug, ip="198.51.100.9")

    assert world.uow.store.links[link.id].reports == 11


async def test_fifty_first_report_of_one_link_in_a_day_is_rate_limited(
    world: LinksWorld,
) -> None:
    """A flood of anonymous reports on one link stops at fifty a day."""
    link = await _link(world, world.person("Ann"))
    for n in range(50):
        await _report(world, link.slug, ip=f"198.51.{n // 250}.{n % 250}")

    with pytest.raises(RateLimitedError):
        await _report(world, link.slug, ip="203.0.113.77")

    assert world.uow.store.links[link.id].reports == 50
    assert await world.redis.ttl(f"rl:report-link:{link.slug}") == 86400


async def test_queue_orders_by_report_count_then_recency(
    world: LinksWorld, clock: FixedClock
) -> None:
    """UF-ADM-10: most reported first, then newest."""
    ann, admin = world.person("Ann"), world.person("Root", Role.ADMIN)
    quiet = await _link(world, ann, "quiet")
    busy = await _link(world, ann, "busy")
    recent = await _link(world, ann, "recent")
    await _link(world, ann, "never-reported")
    await _report(world, quiet.slug)
    clock.advance(minutes=1)
    for ip in ("198.51.100.1", "198.51.100.2", "198.51.100.3"):
        await _report(world, busy.slug, ip=ip)
    clock.advance(minutes=1)
    await _report(world, recent.slug)

    page = await world.services.list_moderation_queue.execute(admin)

    assert [v.link.link.id for v in page.items] == [busy.id, recent.id, quiet.id]
    assert page.next_cursor is None
    assert page.items[0].owner is not None
    assert page.items[0].owner.first_name == "Ann"


async def test_queue_pages_with_a_cursor(world: LinksWorld, clock: FixedClock) -> None:
    """UF-ADM-10: cursor pagination keeps the order."""
    ann, admin = world.person("Ann"), world.person("Root", Role.ADMIN)
    links = [await _link(world, ann, str(i)) for i in range(5)]
    for link in links:
        await _report(world, link.slug)
        clock.advance(minutes=1)

    first = await world.services.list_moderation_queue.execute(admin, limit=2)
    second = await world.services.list_moderation_queue.execute(
        admin, limit=2, cursor=first.next_cursor
    )
    third = await world.services.list_moderation_queue.execute(
        admin, limit=2, cursor=second.next_cursor
    )

    ids = [v.link.link.id for p in (first, second, third) for v in p.items]
    assert ids == [link.id for link in reversed(links)]
    assert third.next_cursor is None


async def test_dismissing_removes_a_link_until_the_next_report(
    world: LinksWorld, clock: FixedClock
) -> None:
    """UF-ADM-10 2a: dismiss clears the queue entry; a new report brings it back."""
    ann, admin = world.person("Ann"), world.person("Root", Role.ADMIN)
    link = await _link(world, ann)
    await _report(world, link.slug)

    await world.services.dismiss_reports.execute(admin, link.id)
    after_dismiss = await world.services.list_moderation_queue.execute(admin)
    clock.advance(minutes=5)
    await _report(world, link.slug)
    after_new_report = await world.services.list_moderation_queue.execute(admin)

    assert after_dismiss.items == []
    assert [v.link.link.id for v in after_new_report.items] == [link.id]


async def test_disabling_records_who_why_and_audits(world: LinksWorld) -> None:
    """SL-8, ADM-13: disable keeps the row as evidence."""
    ann, admin = world.person("Ann"), world.person("Root", Role.ADMIN)
    link = await _link(world, ann)
    await _report(world, link.slug)

    item = await world.services.disable_link.execute(admin, link.id, " phishing ")

    stored = world.uow.store.links[link.id]
    assert stored.is_disabled
    assert stored.disabled_by == admin.user_id
    assert stored.disabled_reason == "phishing"
    assert item.link.link.disabled_reason == "phishing"
    audit = world.uow.store.audits[-1]
    assert (audit.type, audit.user_id, audit.actor_id) == (
        "link.disabled",
        ann.user_id,
        admin.user_id,
    )
    queue = await world.services.list_moderation_queue.execute(admin)
    assert queue.items == []


async def test_disabling_a_lesson_resource_clears_the_room_page(
    world: LinksWorld,
) -> None:
    """UF-ADM-10 step 3: room page caches are cleared."""
    teacher, student = world.person("Galina", Role.TEACHER), world.person("Aleksey")
    admin = world.person("Root", Role.ADMIN)
    room = world.schedule.add_room("102")
    lesson = world.schedule.add_lesson(
        teacher_id=teacher.user_id, room=room, students=[student.user_id]
    )
    views = await world.services.add_lesson_resources.execute(
        student,
        lesson.id,
        role=LessonRole.ATTACHMENT,
        kind=LinkKind.URL,
        target_url="https://example.org/x",
    )
    key = f"room:102:{date(2026, 10, 6).isoformat()}"
    await world.redis.set(key, "<html>cached</html>")

    await world.services.disable_link.execute(admin, views[0].link.id, "offensive")

    assert await world.redis.get(key) is None
    assert await world.services.list_lesson_resources.execute(teacher, lesson.id) == []


async def test_only_admins_moderate(world: LinksWorld) -> None:
    """ADM-13: moderation is for Administration."""
    teacher = world.person("Galina", Role.TEACHER)
    link = await _link(world, world.person("Ann"))

    with pytest.raises(ForbiddenError):
        await world.services.list_moderation_queue.execute(teacher)
    with pytest.raises(ForbiddenError):
        await world.services.search_moderation.execute(teacher, link.slug)
    with pytest.raises(ForbiddenError):
        await world.services.disable_link.execute(teacher, link.id, "x")
    with pytest.raises(ForbiddenError):
        await world.services.dismiss_reports.execute(teacher, link.id)


async def test_disable_of_an_unknown_link_is_a_404(world: LinksWorld) -> None:
    """ADM-13: missing links answer 404."""
    admin = world.person("Root", Role.ADMIN)

    with pytest.raises(LinkNotFoundError):
        await world.services.disable_link.execute(admin, new_id(), "x")


async def test_search_by_slug_url_and_owner(world: LinksWorld) -> None:
    """UF-ADM-10: search by short ID, share URL or user."""
    ann, bob = world.person("Ann"), world.person("Bob")
    admin = world.person("Root", Role.ADMIN)
    anns = [await _link(world, ann, "1"), await _link(world, ann, "2")]
    bobs = await _link(world, bob, "3")
    chat = world.ai.add_chat(ann.user_id, [("user", "a")])
    share = (
        await world.services.create_share.execute(
            ann, kind=LinkKind.CHAT, target_id=chat
        )
    ).link

    by_slug = await world.services.search_moderation.execute(admin, bobs.slug)
    by_url = await world.services.search_moderation.execute(
        admin, f"https://s.ihsu.uz/ai/{share.slug}"
    )
    by_login = await world.services.search_moderation.execute(admin, "ann.ann")
    nothing = await world.services.search_moderation.execute(admin, "  ")

    assert [v.link.link.id for v in by_slug] == [bobs.id]
    assert [v.link.link.id for v in by_url][0] == share.id
    assert {v.link.link.id for v in by_login} == {anns[0].id, anns[1].id, share.id}
    assert nothing == []


async def test_old_reports_survive_in_the_queue(
    world: LinksWorld, clock: FixedClock
) -> None:
    """UF-ADM-10: the queue has no expiry."""
    admin = world.person("Root", Role.ADMIN)
    link = await _link(world, world.person("Ann"))
    await _report(world, link.slug)
    clock.advance(hours=24 * 7)

    queue = await world.services.list_moderation_queue.execute(admin)

    assert [v.link.link.id for v in queue.items] == [link.id]
