"""WEB-6, UF-WEB-04: the secret iCal feed."""

import datetime as dt

from app.shared.actor import Role
from app.shared.ids import hash_token, new_id
from tests.composition.conftest import ClientFor, World, actor_of
from tests.composition.fakes import make_lesson

from icalendar import Calendar


def token_of(url: str) -> str:
    """Cut the token out of `<api>/ical/<token>.ics`."""
    return url.rsplit("/ical/", 1)[1].removesuffix(".ics")


def weekly_lessons(world: World) -> list[dt.date]:
    """Project one lesson a week over the whole term; return their dates."""
    days = [dt.date(2026, 9, 2) + dt.timedelta(weeks=n) for n in range(17)]
    world.schedule.projected = [make_lesson(day=day) for day in days]
    return days


async def test_the_first_call_creates_a_url_and_stores_only_the_hash(
    world: World, client_for: ClientFor
) -> None:
    """WEB-6: the URL is shown once; the backend keeps the SHA-256 only."""
    student = world.add_student()
    client = await client_for(actor_of(student))

    response = await client.post("/v1/me/calendar-token")

    assert response.status_code == 200
    url = response.json()["url"]
    assert url.startswith(f"{world.settings.urls.api}/ical/")
    assert url.endswith(".ics")
    token = token_of(url)
    assert len(token) >= 32
    assert world.tokens.hashes == {student.id: hash_token(token)}


async def test_regenerating_disables_the_old_url(
    world: World, client_for: ClientFor
) -> None:
    """UF-WEB-04: Regenerate creates a new URL and disables the old one."""
    student = world.add_student()
    client = await client_for(actor_of(student))
    first = token_of((await client.post("/v1/me/calendar-token")).json()["url"])
    second = token_of((await client.post("/v1/me/calendar-token")).json()["url"])

    old = await client.get(f"/ical/{first}.ics")
    new = await client.get(f"/ical/{second}.ics")

    assert first != second
    assert old.status_code == 404
    assert new.status_code == 200


async def test_only_students_get_a_calendar_url(
    world: World, client_for: ClientFor
) -> None:
    """POST /v1/me/calendar-token is for students."""
    teacher = world.add_user(Role.TEACHER)
    client = await client_for(actor_of(teacher))

    response = await client.post("/v1/me/calendar-token")

    assert response.status_code == 403


async def test_a_student_without_a_record_cannot_subscribe(
    world: World, client_for: ClientFor
) -> None:
    """WEB-6: nothing to put into a calendar yet."""
    user = world.add_user(Role.STUDENT)
    client = await client_for(actor_of(user))

    response = await client.post("/v1/me/calendar-token")

    assert response.status_code == 404
    assert response.json()["type"] == "composition/student-not-found"


async def test_feed_holds_the_whole_term_not_only_the_next_two_weeks(
    world: World, client_for: ClientFor
) -> None:
    """WEB-6: lessons for the whole term, projected from the timetable."""
    student = world.add_student()
    days = weekly_lessons(world)
    client = await client_for(actor_of(student))
    token = token_of((await client.post("/v1/me/calendar-token")).json()["url"])

    response = await client.get(f"/ical/{token}.ics")

    calendar = Calendar.from_ical(response.content)
    starts = [e.decoded("dtstart") for e in calendar.walk("VEVENT")]
    assert len(starts) == len(days)
    today = dt.date(2026, 10, 6)
    assert any(s.date() > today + dt.timedelta(days=14) for s in starts)
    assert world.schedule.projected_calls == [
        (student.id, dt.date(2026, 9, 2), dt.date(2026, 12, 30))
    ]


async def test_an_event_describes_the_lesson(
    world: World, client_for: ClientFor
) -> None:
    """WEB-6: summary = subject, location = room, description = teacher and topic."""
    student = world.add_student()
    teacher = world.add_user(Role.TEACHER, first_name="Nodira", last_name="Aliyeva")
    lesson = make_lesson(
        day=dt.date(2026, 10, 8),
        period=2,
        subject="Mathematics",
        room="204",
        topic="Limits",
        teacher_id=teacher.id,
    )
    world.schedule.projected = [lesson]
    client = await client_for(actor_of(student))
    token = token_of((await client.post("/v1/me/calendar-token")).json()["url"])

    response = await client.get(f"/ical/{token}.ics")

    [event] = Calendar.from_ical(response.content).walk("VEVENT")
    assert str(event["uid"]) == str(lesson.id)
    assert str(event["summary"]) == "Mathematics"
    assert str(event["location"]) == "204"
    assert str(event["description"]) == "Aliyeva Nodira\nLimits"
    assert event.decoded("dtstart") == lesson.starts_at
    assert event.decoded("dtend") == lesson.ends_at
    assert event.decoded("dtstart").utcoffset() == dt.timedelta(0)
    assert b"DTSTART:20261008T042500Z" in response.content
    assert str(event["status"]) == "CONFIRMED"


async def test_a_cancelled_lesson_is_marked_cancelled(
    world: World, client_for: ClientFor
) -> None:
    """WEB-6: the calendar app strikes the lesson through."""
    student = world.add_student()
    world.schedule.projected = [make_lesson(status="cancelled")]
    client = await client_for(actor_of(student))
    token = token_of((await client.post("/v1/me/calendar-token")).json()["url"])

    response = await client.get(f"/ical/{token}.ics")

    [event] = Calendar.from_ical(response.content).walk("VEVENT")
    assert str(event["status"]) == "CANCELLED"


async def test_feed_is_served_as_calendar_without_a_login_and_cached(
    world: World, client_for: ClientFor
) -> None:
    """WEB-6: calendar apps cannot log in; the feed may be cached for 15 minutes."""
    student = world.add_student()
    token = token_of(
        (
            await (await client_for(actor_of(student))).post("/v1/me/calendar-token")
        ).json()["url"]
    )
    anonymous = await client_for(None)

    response = await anonymous.get(f"/ical/{token}.ics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert response.headers["cache-control"] == "max-age=900"
    assert response.content.startswith(b"BEGIN:VCALENDAR")


async def test_an_unknown_token_is_not_found(
    world: World, client_for: ClientFor
) -> None:
    """WEB-6: an invalid link answers 404."""
    client = await client_for(None)

    response = await client.get(f"/ical/{new_id().hex}{new_id().hex}.ics")

    assert response.status_code == 404
    assert response.json()["type"] == "calendar/feed-not-found"


async def test_a_token_of_the_wrong_length_never_reaches_the_store(
    world: World, client_for: ClientFor
) -> None:
    """WEB-6: short and huge tokens are rejected before hashing."""
    client = await client_for(None)

    short = await client.get("/ical/abc.ics")
    huge = await client.get(f"/ical/{'x' * 500}.ics")

    assert (short.status_code, huge.status_code) == (404, 404)
    assert world.tokens.lookups == []


async def test_without_a_term_the_feed_is_an_empty_calendar(
    world: World, client_for: ClientFor
) -> None:
    """WEB-6: the subscription stays valid between terms."""
    student = world.add_student()
    world.overview.bounds = None
    client = await client_for(actor_of(student))
    token = token_of((await client.post("/v1/me/calendar-token")).json()["url"])

    response = await client.get(f"/ical/{token}.ics")

    assert response.status_code == 200
    assert list(Calendar.from_ical(response.content).walk("VEVENT")) == []
    assert world.schedule.projected_calls == []
