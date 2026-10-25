"""SL-4, SL-6, SL-7, SL-8, SL-10, UF-PUB-03: opening short links."""

from datetime import timedelta

from app.modules.links.application.views import WebResponse
from app.modules.links.domain.link import LessonRole, Link, LinkKind
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.links.world import LinksWorld

IP = "203.0.113.7"


async def _open(
    world: LinksWorld, slug: str, lang: str | None = None, ip: str = IP
) -> WebResponse:
    return await world.services.open_short_link.execute(
        slug, ip=ip, accept_language=lang
    )


async def _url_link(world: LinksWorld, url: str) -> Link:
    ann = world.people.get("Ann") or world.person("Ann")
    return (
        await world.services.create_link.execute(ann, kind=LinkKind.URL, target_url=url)
    ).link


async def test_allowlisted_url_redirects_with_302(world: LinksWorld) -> None:
    """SL-4: trusted domains redirect directly."""
    link = await _url_link(world, "https://en.wikipedia.org/wiki/Physics")

    result = await _open(world, link.slug)

    assert result.status_code == 302
    assert result.location == "https://en.wikipedia.org/wiki/Physics"


async def test_other_domains_show_an_interstitial_with_the_full_destination(
    world: LinksWorld,
) -> None:
    """SL-4: the page shows the full destination, Continue and Report."""
    link = await _url_link(world, "https://example.org/a?b=1&c=2")

    result = await _open(world, link.slug, lang="en")

    assert result.status_code == 200
    assert result.location is None
    assert result.html is not None
    assert "https://example.org/a?b=1&amp;c=2" in result.html
    assert 'href="https://example.org/a?b=1&amp;c=2"' in result.html
    assert "Continue" in result.html
    assert f"/s/{link.slug}/report" in result.html
    assert 'name="robots" content="noindex"' in result.html
    assert 'name="referrer" content="no-referrer"' in result.html


async def test_interstitial_is_localized(world: LinksWorld) -> None:
    """SL-4: uz, ru and en."""
    link = await _url_link(world, "https://example.org/")

    ru = await _open(world, link.slug, lang="ru-RU,ru;q=0.9")
    uz = await _open(world, link.slug, lang="uz")

    assert ru.html is not None and "Продолжить" in ru.html
    assert uz.html is not None and "Davom etish" in uz.html


async def test_file_link_redirects_to_a_presigned_url(world: LinksWorld) -> None:
    """FILE-3, UF-PUB-03: files redirect to storage."""
    ann = world.person("Ann")
    file = world.files.add(ann.user_id)
    view = await world.services.create_link.execute(
        ann, kind=LinkKind.FILE, file_id=file.id
    )

    result = await _open(world, view.link.slug)

    assert result.status_code == 302
    assert result.location == f"https://storage.test/{file.id}?sig=abc"


async def test_file_deleted_in_the_files_module_answers_410(world: LinksWorld) -> None:
    """FILE cleanup: a link to a deleted file is gone."""
    ann = world.person("Ann")
    file = world.files.add(ann.user_id)
    view = await world.services.create_link.execute(
        ann, kind=LinkKind.FILE, file_id=file.id
    )
    del world.files.files[file.id]

    result = await _open(world, view.link.slug)

    assert result.status_code == 410


async def test_every_open_counts_a_hit_in_redis(world: LinksWorld) -> None:
    """SL-6: clicks are counted, flushed later."""
    link = await _url_link(world, "https://en.wikipedia.org/wiki/Physics")

    await _open(world, link.slug)
    await _open(world, link.slug)

    assert await world.redis.get(f"links:hits:{link.id}") == "2"


async def test_revoked_link_answers_410(world: LinksWorld) -> None:
    """SL-7: deleted links are gone, not missing."""
    ann = world.person("Ann")
    link = await _url_link(world, "https://example.org/")
    await world.services.delete_link.execute(ann, link.id)

    result = await _open(world, link.slug, lang="en")

    assert result.status_code == 410
    assert result.html is not None and "removed" in result.html
    assert await world.redis.get(f"links:hits:{link.id}") is None


async def test_expired_link_answers_410(world: LinksWorld, clock: FixedClock) -> None:
    """SL-7: expired links are gone."""
    link = await _url_link(world, "https://example.org/")
    stored = world.uow.store.links[link.id]
    stored.expires_at = clock.now() + timedelta(minutes=1)
    clock.advance(minutes=2)

    assert (await _open(world, link.slug)).status_code == 410


async def test_disabled_link_shows_the_disabled_page(world: LinksWorld) -> None:
    """SL-8, UF-PUB-03 1c: Administration disabled it."""
    admin = world.person("Root", Role.ADMIN)
    link = await _url_link(world, "https://example.org/")
    await world.services.disable_link.execute(admin, link.id, "phishing")

    result = await _open(world, link.slug, lang="en")

    assert result.status_code == 410
    assert result.html is not None and "disabled" in result.html


async def test_url_added_to_the_blocklist_later_is_not_followed(
    world: LinksWorld,
) -> None:
    """SL-8: the blocklist is checked again on open."""
    link = await _url_link(world, "https://example.org/")
    world.uow.store.links[link.id].target_url = "https://blocked.example/x"

    result = await _open(world, link.slug)

    assert result.location is None
    assert result.status_code == 410


async def test_hidden_lesson_resource_does_not_open(world: LinksWorld) -> None:
    """STF-6: hidden attachments are removed for everybody."""
    teacher = world.person("Galina", Role.TEACHER)
    student = world.person("Aleksey")
    lesson = world.schedule.add_lesson(
        teacher_id=teacher.user_id, students=[student.user_id]
    )
    views = await world.services.add_lesson_resources.execute(
        student,
        lesson.id,
        role=LessonRole.ATTACHMENT,
        kind=LinkKind.URL,
        target_url="https://en.wikipedia.org/wiki/Physics",
    )
    await world.services.hide_lesson_resource.execute(
        teacher, lesson.id, views[0].link.id, hidden=True
    )

    assert (await _open(world, views[0].link.slug)).status_code == 410


async def test_unknown_slug_is_a_404(world: LinksWorld) -> None:
    """SL-7, UF-PUB-03 1a: IDs that never existed."""
    result = await _open(world, "zzz", lang="en")

    assert result.status_code == 404
    assert result.html is not None and "not found" in result.html.lower()


async def test_share_slugs_are_not_served_on_the_short_link_host(
    world: LinksWorld,
) -> None:
    """SHR-1: shares live under /ai/, not at the short link root."""
    ann = world.person("Ann")
    cards = world.flashcards.add_set(ann.user_id, [("a", "b")])
    share = await world.services.create_share.execute(
        ann, kind=LinkKind.FLASHCARD_SET, target_id=cards
    )

    assert (await _open(world, share.link.slug)).status_code == 404


async def test_sixty_first_404_from_one_ip_is_rate_limited(world: LinksWorld) -> None:
    """SL-10: 404s are rate limited per IP (60 per 10 minutes)."""
    for index in range(60):
        result = await _open(world, f"nope{index}")
        assert result.status_code == 404

    blocked = await _open(world, "nope-more")
    other_ip = await _open(world, "nope-more", ip="198.51.100.9")

    assert blocked.status_code == 429
    assert blocked.retry_after is not None and blocked.retry_after > 0
    assert other_ip.status_code == 404


async def test_reserved_names_are_404_without_using_the_budget(
    world: LinksWorld,
) -> None:
    """SL-2: browsers asking for favicon.ico must not burn the 404 budget."""
    for _ in range(100):
        assert (await _open(world, "favicon.ico")).status_code == 404

    assert (await _open(world, "zzz")).status_code == 404


async def test_garbage_slugs_are_404_without_a_database_lookup(
    world: LinksWorld,
) -> None:
    """SL-10: scanners guessing paths cost nothing but budget."""
    for slug in ["x" * 100, "a b", "admin.php", str(new_id())]:
        assert (await _open(world, slug)).status_code == 404
    assert world.uow.store.commits == 0
