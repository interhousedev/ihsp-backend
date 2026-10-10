"""ROOM-1..ROOM-8, UF-PUB-04: the room page and its PIN."""

import re
from datetime import UTC, date, datetime

from app.modules.links.application.views import WebResponse
from app.modules.links.domain.link import LessonRole, LinkKind
from app.shared.actor import Role
from tests.fakes.clock import FixedClock
from tests.fakes.links.world import LinksWorld

import pytest

IP = "203.0.113.7"
PIN = "483920"
TODAY = date(2026, 10, 6)


async def _page(
    world: LinksWorld,
    slug: str = "102",
    *,
    pin: str | None = PIN,
    day: str | None = None,
    ip: str = IP,
    lang: str | None = "en",
) -> WebResponse:
    return await world.services.render_room_page.execute(
        slug, pin=pin, day=day, ip=ip, accept_language=lang
    )


async def _classroom(world: LinksWorld, clock: FixedClock) -> None:
    """Physics in room 102 with a material and two attachments by two students."""
    clock.set(datetime(2026, 10, 6, 5, 0, tzinfo=UTC))  # 10:00 in Tashkent
    teacher = world.person("Galina", Role.TEACHER, last_name="Kalandarova")
    aleksey, madina = world.person("Aleksey"), world.person("Madina")
    room = world.schedule.add_room("102", pin=PIN)
    lesson = world.schedule.add_lesson(
        teacher_id=teacher.user_id,
        room=room,
        students=[aleksey.user_id, madina.user_id],
        group_names=("2TN2",),
    )
    world.schedule.add_lesson(
        period=4, subject_name="English", group_names=("2TN1/2",), room=room
    )
    add = world.services.add_lesson_resources.execute
    await add(
        teacher,
        lesson.id,
        role=LessonRole.MATERIAL,
        kind=LinkKind.URL,
        target_url="https://example.org/lecture",
    )
    await add(
        aleksey,
        lesson.id,
        role=LessonRole.ATTACHMENT,
        kind=LinkKind.URL,
        target_url="https://example.org/derivatives",
    )
    file = world.files.add(aleksey.user_id, name="Derivatives.pdf")
    await add(
        aleksey,
        lesson.id,
        role=LessonRole.ATTACHMENT,
        kind=LinkKind.FILE,
        file_id=file.id,
    )
    await add(
        madina,
        lesson.id,
        role=LessonRole.ATTACHMENT,
        kind=LinkKind.URL,
        target_url="https://example.org/answers",
    )


async def test_without_a_pin_only_the_form_is_shown(world: LinksWorld) -> None:
    """ROOM-2, UF-PUB-04 step 1: a PIN form and nothing else."""
    world.schedule.add_room("102", pin=PIN)

    result = await _page(world, pin=None)

    assert result.status_code == 200
    assert result.html is not None
    assert '<form method="get"' in result.html
    assert 'name="pin"' in result.html
    assert "Physics" not in result.html


async def test_the_form_keeps_the_requested_date(world: LinksWorld) -> None:
    """ROOM-4: previous days work after typing the PIN."""
    world.schedule.add_room("102", pin=PIN)

    result = await _page(world, pin=None, day="2026-10-05")

    assert result.html is not None
    assert '<input type="hidden" name="date" value="2026-10-05">' in result.html


async def test_wrong_pin_shows_the_form_with_an_error(world: LinksWorld) -> None:
    """UF-PUB-04 1a: Wrong PIN."""
    world.schedule.add_room("102", pin=PIN)

    result = await _page(world, pin="000000")

    assert result.status_code == 403
    assert result.html is not None and "Wrong PIN" in result.html


async def test_five_wrong_pins_then_even_the_right_one_gets_429(
    world: LinksWorld,
) -> None:
    """ROOM-5: five attempts per fifteen minutes per IP and room."""
    world.schedule.add_room("102", pin=PIN)
    for _ in range(5):
        assert (await _page(world, pin="000000")).status_code == 403

    blocked = await _page(world, pin=PIN)
    other_ip = await _page(world, pin=PIN, ip="198.51.100.9")

    assert blocked.status_code == 429
    assert blocked.retry_after is not None and 0 < blocked.retry_after <= 900
    assert other_ip.status_code == 200


async def test_the_block_ends_after_fifteen_minutes(
    world: LinksWorld, clock: FixedClock
) -> None:
    """ROOM-5: the window is fifteen minutes (Redis TTL)."""
    world.schedule.add_room("102", pin=PIN)
    for _ in range(5):
        await _page(world, pin="000000")
    await world.redis.delete(f"rl:room-pin:102:{IP}")  # what the TTL does in Redis

    assert (await _page(world, pin=PIN)).status_code == 200


async def test_attempts_are_counted_per_room(world: LinksWorld) -> None:
    """ROOM-5: wrong PINs of one room do not block another."""
    world.schedule.add_room("102", pin=PIN)
    world.schedule.add_room("204", pin="111111")
    for _ in range(5):
        await _page(world, "102", pin="000000")

    assert (await _page(world, "204", pin="111111")).status_code == 200


async def test_right_pin_shows_the_day_with_now_marker_and_resources(
    world: LinksWorld, clock: FixedClock
) -> None:
    """ROOM-4, UF-PUB-04 step 3: lessons by period, [now], materials, authors."""
    await _classroom(world, clock)

    result = await _page(world)

    assert result.status_code == 200
    html = result.html
    assert html is not None
    assert "localhost:8000/r/102 · Tuesday 06.10" in html
    assert "[now] 3  09:55–10:40  Physics · 2TN2 · Kalandarova G." in html
    assert "      4  10:50–11:35  English · 2TN1/2" in html
    assert "Materials: <a href=" in html
    assert "(Title of https://example.org/lecture)" in html
    assert "Aleksey - <a href=" in html
    assert "Madina  - <a href=" in html
    assert "(Derivatives.pdf)" in html
    assert html.index("Materials:") < html.index("Aleksey")
    assert html.index("Aleksey") < html.index("Madina")
    assert html.count("[now]") == 1
    assert "Previous days:" in html


async def test_every_resource_has_a_report_link(
    world: LinksWorld, clock: FixedClock
) -> None:
    """SL-9: room pages offer Report next to links."""
    await _classroom(world, clock)

    result = await _page(world)

    assert result.html is not None
    assert result.html.count("[report]") == 4
    assert "/s/" in result.html and "/report" in result.html


async def test_previous_days_skip_weekends_and_keep_the_pin(
    world: LinksWorld, clock: FixedClock
) -> None:
    """ROOM-4: the last seven study days (Mon-Fri) link back with ?pin=&date=."""
    await _classroom(world, clock)

    result = await _page(world)

    assert result.html is not None
    html = result.html
    shown = re.findall(r"date=(\d{4}-\d{2}-\d{2})\">", html)
    assert shown == [
        "2026-10-05",
        "2026-10-02",  # 2026-10-03 and 2026-10-04 are a Saturday and a Sunday
        "2026-10-01",
        "2026-09-30",
        "2026-09-29",
        "2026-09-28",
        "2026-09-25",  # 2026-09-26 and 2026-09-27 are a weekend
    ]
    assert html.count(f"?pin={PIN}&amp;date=") == 7
    assert "__PIN__" not in html


async def test_a_saturday_shows_its_date_without_a_weekday_name(
    world: LinksWorld, clock: FixedClock
) -> None:
    """ROOM-4: the lyceum does not study on Saturday; an old link still opens."""
    await _classroom(world, clock)

    result = await _page(world, day="2026-10-03")

    assert result.status_code == 200
    assert result.html is not None
    assert "Saturday" not in result.html
    assert "No lessons in room 102 on 03.10" in result.html


async def test_a_past_day_has_no_now_marker_and_links_back_to_today(
    world: LinksWorld, clock: FixedClock
) -> None:
    """ROOM-4: previous days show lessons of that day."""
    await _classroom(world, clock)
    world.schedule.add_lesson(
        day=date(2026, 10, 5),
        subject_name="Chemistry",
        room=world.schedule.rooms["102"],
        teacher_id=None,
    )

    result = await _page(world, day="2026-10-05")

    assert result.html is not None
    assert "Chemistry" in result.html
    assert "Physics" not in result.html
    assert "[now]" not in result.html
    assert "Monday 05.10" in result.html
    assert ">Today</a>" in result.html


async def test_a_day_without_lessons_says_so(
    world: LinksWorld, clock: FixedClock
) -> None:
    """UF-PUB-04 3a: no lessons today."""
    clock.set(datetime(2026, 10, 6, 5, 0, tzinfo=UTC))
    world.schedule.add_room("102", pin=PIN)

    result = await _page(world)

    assert result.html is not None
    assert "No lessons in room 102 today" in result.html
    assert "Previous days:" in result.html


@pytest.mark.parametrize("day", ["garbage", "2999-01-01", "1999-01-01", "2026-13-40"])
async def test_odd_dates_fall_back_to_a_sane_day(
    world: LinksWorld, clock: FixedClock, day: str
) -> None:
    """ROOM-8: arbitrary dates cannot fill the cache."""
    await _classroom(world, clock)

    result = await _page(world, day=day)

    assert result.status_code == 200
    keys = [k async for k in world.redis.scan_iter(match="room:*")]
    assert len(keys) == 1


async def test_cancelled_lessons_are_marked(
    world: LinksWorld, clock: FixedClock
) -> None:
    """ROOM-4: changed lessons stay visible."""
    clock.set(datetime(2026, 10, 6, 5, 0, tzinfo=UTC))
    room = world.schedule.add_room("102", pin=PIN)
    world.schedule.add_lesson(room=room, status="cancelled")

    result = await _page(world)

    assert result.html is not None
    assert "[cancelled]" in result.html
    assert "[now]" not in result.html


async def test_hidden_and_disabled_resources_are_left_out(
    world: LinksWorld, clock: FixedClock
) -> None:
    """STF-6, ADM-13: hidden or disabled resources disappear from the room page."""
    await _classroom(world, clock)
    teacher = world.people["Galina"]
    admin = world.person("Root", Role.ADMIN)
    lesson = next(iter(world.schedule.lessons.values()))
    links = [x for x in world.uow.store.links.values() if x.lesson_id == lesson.id]
    madina, aleksey = world.user_id("Madina"), world.user_id("Aleksey")
    madina_link = next(x for x in links if x.owner_id == madina)
    aleksey_url = next(x for x in links if x.owner_id == aleksey and x.target_url)

    await world.services.hide_lesson_resource.execute(
        teacher, lesson.id, madina_link.id, hidden=True
    )
    await world.services.disable_link.execute(admin, aleksey_url.id, "offensive")
    result = await _page(world)

    assert result.html is not None
    assert "Madina" not in result.html
    assert "(Derivatives.pdf)" in result.html
    assert result.html.count("[report]") == 2


async def test_pages_are_cached_and_cleared_when_a_resource_is_added(
    world: LinksWorld, clock: FixedClock
) -> None:
    """ROOM-8: cached for ten minutes, refreshed on change."""
    await _classroom(world, clock)
    first = await _page(world)
    key = f"room:102:{TODAY.isoformat()}"
    assert await world.redis.ttl(key) == 600
    cached = await world.redis.get(key)
    assert cached is not None and PIN not in cached  # the PIN is filled in on serving

    lesson = next(iter(world.schedule.lessons.values()))
    madina = world.people["Madina"]
    await world.services.add_lesson_resources.execute(
        madina,
        lesson.id,
        role=LessonRole.ATTACHMENT,
        kind=LinkKind.URL,
        target_url="https://example.org/new",
    )
    assert await world.redis.get(key) is None
    second = await _page(world)

    assert first.html is not None and second.html is not None
    assert second.html.count("[report]") == first.html.count("[report]") + 1


async def test_changing_the_pin_works_with_the_cached_page(
    world: LinksWorld, clock: FixedClock
) -> None:
    """ROOM-6: a regenerated PIN opens the cached page; the old one does not."""
    await _classroom(world, clock)
    await _page(world)
    room = world.schedule.rooms["102"]
    world.schedule.rooms["102"] = type(room)(
        id=room.id, slug=room.slug, name=room.name, pin="999999", status="active"
    )

    old = await _page(world, pin=PIN)
    new = await _page(world, pin="999999")

    assert old.status_code == 403
    assert new.status_code == 200
    assert new.html is not None and "pin=999999" in new.html


async def test_unknown_and_archived_rooms_are_404(world: LinksWorld) -> None:
    """UF-PUB-04: unknown or archived room."""
    world.schedule.add_room("old", pin=PIN, status="archived")

    assert (await _page(world, "missing")).status_code == 404
    assert (await _page(world, "old")).status_code == 404


async def test_sixty_one_missing_rooms_from_one_ip_are_rate_limited(
    world: LinksWorld,
) -> None:
    """SL-10: 404s on ihsu.uz/r/ share the per-IP budget."""
    for index in range(60):
        assert (await _page(world, f"room{index}")).status_code == 404

    assert (await _page(world, "room-more")).status_code == 429


async def test_room_form_is_localized(world: LinksWorld) -> None:
    """ROOM-2: the PIN form follows Accept-Language."""
    world.schedule.add_room("102", pin=PIN)

    result = await _page(world, pin=None, lang="ru")

    assert result.html is not None and "Введите 6-значный PIN" in result.html
