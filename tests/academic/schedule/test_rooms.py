"""Rooms: names, PIN, rename, merge, archive (ROOM-1, ROOM-6, ROOM-7, ADM-19)."""

import datetime as dt

from app.modules.academic.application.schedule.ensure_room import ensure_room_in
from app.modules.academic.domain.schedule.errors import (
    RoomInUseError,
    RoomMergeInvalidError,
    RoomNameInvalidError,
    RoomNotFoundError,
    RoomSlugTakenError,
)
from app.shared.ids import new_id
from tests.academic.schedule.env import ROOMS_URL, TODAY, Env

import pytest


async def test_a_new_room_gets_a_slug_and_a_six_digit_pin(env: Env) -> None:
    """ROOM-1, ROOM-2: 'Кластер' becomes klaster with a random 6-digit PIN."""
    room = await env.services.ensure_room.execute("Кластер")

    assert (room.slug, room.name) == ("klaster", "Кластер")
    assert len(room.pin) == 6 and room.pin.isdigit()
    assert room.status == "active"


async def test_typing_the_same_name_again_reuses_the_room(env: Env) -> None:
    """ROOM-1: the second timetable entry in 102 does not create a second room."""
    first = await env.services.ensure_room.execute("102")
    second = await env.services.ensure_room.execute(" 102 ")

    assert second.id == first.id and second.pin == first.pin


async def test_a_name_without_letters_or_digits_gets_the_fallback_slug(
    env: Env,
) -> None:
    """ROOM-1: slug = slugify(name) or 'room'."""
    room = await env.services.ensure_room.execute("???")

    assert room.slug == "room"


async def test_an_empty_room_name_is_invalid(env: Env) -> None:
    """ROOM-1: a blank name creates nothing."""
    with pytest.raises(RoomNameInvalidError):
        await env.services.ensure_room.execute("   ")


async def test_a_merged_room_leads_to_the_room_it_was_merged_into(env: Env) -> None:
    """ROOM-7: typing the mistyped name again lands in the right room."""
    typo = await env.room("1O2")
    right = await env.room("102")
    await env.services.merge_room.execute(typo.id, right.id)

    found = await env.services.ensure_room.execute("1O2")

    assert found.id == right.id


async def test_an_archived_room_is_reopened_when_its_name_is_used_again(
    env: Env,
) -> None:
    """ROOM-7: archiving is not a permanent ban."""
    room = await env.room("102")
    await env.services.archive_room.execute(room.id)

    again = await env.services.ensure_room.execute("102")

    assert again.id == room.id and again.status == "active"


async def test_ensure_room_in_works_inside_another_transaction(env: Env) -> None:
    """ROOM-1: use cases create rooms in their own unit of work."""
    async with env.uow_factory() as uow:
        room = await ensure_room_in(uow, "Lab 3", env.clock.now())
        await uow.commit()

    assert room.slug == "lab-3"


async def test_list_rooms_shows_the_link_pin_and_lessons_this_week(env: Env) -> None:
    """ADM-19, UF-ADM-16: the list has link, PIN and number of lessons this week."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    room = await env.room("102")
    quiet = await env.room("103")
    audience = [str(group.id)]
    await env.lesson(
        term,
        day=dt.date(2026, 10, 7),
        period=1,
        subject=subject,
        audience=audience,
        room=room,
    )
    await env.lesson(
        term,
        day=dt.date(2026, 10, 8),
        period=1,
        subject=subject,
        audience=audience,
        room=room,
    )
    await env.lesson(
        term,
        day=dt.date(2026, 10, 13),
        period=1,
        subject=subject,
        audience=audience,
        room=room,
    )

    rooms = {r.slug: r for r in await env.services.list_rooms.execute()}

    assert (
        rooms["102"].lessons_this_week == 2
    )  # 05.10-11.10; the third lesson is next week
    assert rooms["103"].lessons_this_week == 0 and quiet.slug == "103"
    assert rooms["102"].url == f"{ROOMS_URL}/102?pin={room.pin}"


async def test_list_rooms_filters_by_status(env: Env) -> None:
    """ADM-19: ?status=archived."""
    room = await env.room("102")
    await env.room("103")
    await env.services.archive_room.execute(room.id)

    archived = await env.services.list_rooms.execute("archived")

    assert [r.slug for r in archived] == ["102"]


async def test_renaming_changes_the_name_and_the_address(env: Env) -> None:
    """ROOM-7: klaster -> klaster-1."""
    room = await env.room("Кластер")

    renamed = await env.services.rename_room.execute(room.id, "Кластер 1")

    assert (renamed.name, renamed.slug) == ("Кластер 1", "klaster-1")
    assert set(env.cache.invalidated) == {"klaster", "klaster-1"}


async def test_the_new_address_must_be_free(env: Env) -> None:
    """ROOM-7: a rename cannot take another room's address."""
    room = await env.room("102")
    await env.room("103")

    with pytest.raises(RoomSlugTakenError):
        await env.services.rename_room.execute(room.id, "103")


async def test_renaming_with_only_a_different_case_is_allowed(env: Env) -> None:
    """ROOM-7: the room's own slug does not count as taken."""
    room = await env.room("klaster")

    renamed = await env.services.rename_room.execute(room.id, "Klaster")

    assert renamed.slug == "klaster" and renamed.name == "Klaster"


async def test_renaming_an_unknown_room_is_not_found(env: Env) -> None:
    """API: unknown ids answer 404."""
    with pytest.raises(RoomNotFoundError):
        await env.services.rename_room.execute(new_id(), "X")


async def test_regenerating_the_pin_changes_it_and_clears_the_cache(env: Env) -> None:
    """ROOM-6: the old PIN stops working at once."""
    room = await env.room("102")

    updated = await env.services.regenerate_room_pin.execute(room.id)

    assert updated.pin != room.pin and len(updated.pin) == 6
    assert updated.url.endswith(f"?pin={updated.pin}")
    assert env.cache.invalidated == ["102"]


async def test_merging_moves_entries_and_lessons_and_archives_the_source(
    env: Env,
) -> None:
    """ROOM-7, UF-ADM-16 3a: 'Merge into' moves the lessons to the right room."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    typo = await env.room("1O2")
    right = await env.room("102")
    audience = [str(group.id)]
    entry = await env.entry(
        term, weekday=1, period=1, subject=subject, audience=audience, room=typo
    )
    await env.lesson(
        term,
        day=dt.date(2026, 10, 12),
        period=1,
        subject=subject,
        audience=audience,
        room=typo,
        entry=entry,
    )

    target = await env.services.merge_room.execute(typo.id, right.id)

    assert target.id == right.id
    async with env.uow_factory() as uow:
        moved_entry = await uow.entries.get(entry.id)
        source = await uow.rooms.get(typo.id)
    assert moved_entry is not None and moved_entry.room_id == right.id
    assert [lesson.room_id for lesson in await env.lessons()] == [right.id]
    assert source is not None
    assert (source.status, source.merged_into_id) == ("archived", right.id)
    assert set(env.cache.invalidated) == {"1o2", "102"}


async def test_a_room_cannot_be_merged_into_itself_or_an_archived_room(
    env: Env,
) -> None:
    """ROOM-7: merging needs a live target."""
    room = await env.room("102")
    archived = await env.room("103")
    await env.services.archive_room.execute(archived.id)

    with pytest.raises(RoomMergeInvalidError):
        await env.services.merge_room.execute(room.id, room.id)
    with pytest.raises(RoomMergeInvalidError):
        await env.services.merge_room.execute(room.id, archived.id)


async def test_a_room_with_future_lessons_cannot_be_archived(env: Env) -> None:
    """ROOM-7: archive only rooms no lesson uses any more."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    room = await env.room("102")
    await env.lesson(
        term,
        day=dt.date(2026, 10, 7),
        period=1,
        subject=subject,
        audience=[str(group.id)],
        room=room,
    )

    with pytest.raises(RoomInUseError):
        await env.services.archive_room.execute(room.id)


async def test_a_room_with_only_past_lessons_can_be_archived(env: Env) -> None:
    """ROOM-7: lessons that already took place do not block archiving."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    room = await env.room("102")
    await env.lesson(
        term,
        day=TODAY - dt.timedelta(days=3),
        period=1,
        subject=subject,
        audience=[str(group.id)],
        room=room,
    )

    archived = await env.services.archive_room.execute(room.id)

    assert archived.status == "archived"
