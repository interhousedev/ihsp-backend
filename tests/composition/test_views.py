"""JSON views of contract objects (LessonItem, load_users)."""

import dataclasses
from uuid import UUID

from app.interfaces.http.v1.composition.application.views import (
    USER_BATCH,
    audience_items,
    lesson_item,
    load_users,
)
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.composition.fakes import FakeIdentity, make_lesson, make_user


async def test_users_are_loaded_in_batches_without_duplicates() -> None:
    """Large audiences must not become one huge IN list."""
    identity = FakeIdentity()
    users = [identity.add(make_user(Role.TEACHER)) for _ in range(USER_BATCH + 20)]
    ids = [u.id for u in users] + [users[0].id, new_id()]

    loaded = await load_users(identity, ids)

    assert set(loaded) == {u.id for u in users}
    assert identity.get_users_calls == [USER_BATCH, 21]


async def test_nothing_is_loaded_for_no_ids() -> None:
    """No ids, no query."""
    identity = FakeIdentity()

    assert await load_users(identity, []) == {}
    assert identity.get_users_calls == []


def test_a_subgroup_key_gives_the_bare_group_name_and_the_subgroup() -> None:
    """LessonRef.audience keys are `<group>[:<subgroup>]`, labels `2TN2/1`."""
    group = new_id()

    [whole] = audience_items(make_lesson(group_id=group, group_name="2TN2"))
    [half] = audience_items(make_lesson(group_id=group, group_name="2TN2", subgroup=2))

    assert (whole["group_id"], whole["group_name"], whole["subgroup"]) == (
        group,
        "2TN2",
        None,
    )
    assert (half["group_id"], half["group_name"], half["subgroup"]) == (
        group,
        "2TN2",
        2,
    )


def test_a_malformed_audience_key_is_skipped() -> None:
    """A corrupt key must not break a whole list."""
    lesson = dataclasses.replace(
        make_lesson(), audience=("not-a-uuid", str(new_id())), group_names=("x", "1TN1")
    )

    items = audience_items(lesson)

    assert [i["group_name"] for i in items] == ["1TN1"]


def test_a_lesson_without_a_room_or_teacher_has_null_parts() -> None:
    """LessonItem: room and teacher are nullable."""
    item = lesson_item(make_lesson(room=None, teacher_id=None), {})

    assert item["room"] is None
    assert item["teacher"] is None
    assert item["has_homework"] is False
    assert (item["is_overridden"], item["changes"]) == (False, None)


def test_an_unknown_teacher_id_gives_a_null_teacher() -> None:
    """A deleted teacher must not break the lesson list."""
    teacher_id: UUID = new_id()

    item = lesson_item(make_lesson(teacher_id=teacher_id), {})

    assert item["teacher"] is None
