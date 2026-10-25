"""UF-SYS-06, UF-BOT-07, UF-BOT-08: lesson reminders run every minute."""

from typing import Any
from uuid import UUID

from app.shared.notifications import NotificationType
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson, local

# The fixed clock is 14:00 in Tashkent.


async def _starting_at_1405(env: Env, **extra: Any) -> UUID:
    return await add_lesson(
        env.maker,
        env.world,
        starts_at=local(DAY, 14, 5),
        ends_at=local(DAY, 14, 50),
        **extra,
    )


async def test_one_resources_message_at_five_minutes_before_the_lesson(
    env: Env,
) -> None:
    """UF-BOT-07: the teacher and the head student get it, once."""
    w = env.world
    lesson_id = await _starting_at_1405(env)
    env.links.add(lesson_id, title="Lecture 5.pdf")
    env.schedule.heads[lesson_id] = [w.aziz.id]

    first = await env.services.lesson_reminders.execute()
    env.clock.advance(minutes=1)
    second = await env.services.lesson_reminders.execute()

    assert first == {"resources": 2, "prompts": 0}
    assert second == {"resources": 0, "prompts": 0}
    drafts = env.outbox.notifications
    assert {d.user_id for d in drafts} == {w.teacher.id, w.aziz.id}
    assert {d.dedupe_key for d in drafts} == {
        f"res:{lesson_id}:{w.teacher.id}",
        f"res:{lesson_id}:{w.aziz.id}",
    }
    assert all(d.type is NotificationType.LESSON_RESOURCES for d in drafts)
    assert drafts[0].payload == {
        "lesson_id": str(lesson_id),
        "group_names": ["2TN2"],
        "subject_name": "Physics",
        "period": 1,
        "room_name": "204",
        "room_url": "http://localhost:8000/r/204?pin=483920",
        "room_pin": "483920",
    }


async def test_nothing_is_sent_for_a_lesson_without_resources(env: Env) -> None:
    """UF-BOT-07 1a: no resources, no message."""
    await _starting_at_1405(env)

    result = await env.services.lesson_reminders.execute()

    assert result == {"resources": 0, "prompts": 0}
    assert env.outbox.notifications == []


async def test_nothing_is_sent_for_a_cancelled_lesson(env: Env) -> None:
    """UF-BOT-07 1a: cancelled lessons send nothing."""
    lesson_id = await _starting_at_1405(env, status="cancelled")
    env.links.add(lesson_id)

    assert await env.services.lesson_reminders.execute() == {
        "resources": 0,
        "prompts": 0,
    }


async def test_message_without_a_room_has_no_room_page_lines(env: Env) -> None:
    """UF-BOT-07 1b: the lesson has no room."""
    lesson_id = await _starting_at_1405(env, room_id=None)
    env.links.add(lesson_id)

    await env.services.lesson_reminders.execute()

    payload = env.outbox.notifications[0].payload
    assert "room_url" not in payload
    assert "room_pin" not in payload
    assert "room_name" not in payload


async def test_each_recipient_uses_their_own_lead_time(env: Env) -> None:
    """STF-10: lessons_links_lead_min is per user."""
    w = env.world
    lesson_id = await _starting_at_1405(env)
    env.links.add(lesson_id)
    env.schedule.heads[lesson_id] = [w.aziz.id]
    env.identity.set_preferences(w.teacher.id, lessons_links_lead_min=10)

    now = await env.services.lesson_reminders.execute()
    env.clock.advance(minutes=-5)  # 13:55: ten minutes before the start
    earlier = await env.services.lesson_reminders.execute()

    assert now == {"resources": 1, "prompts": 0}
    assert earlier == {"resources": 1, "prompts": 0}
    assert [d.user_id for d in env.outbox.notifications] == [w.aziz.id, w.teacher.id]


async def test_one_prompt_five_minutes_before_the_lesson_ends(env: Env) -> None:
    """UF-BOT-08: the teacher gets the attendance prompt once."""
    w = env.world
    lesson_id = await add_lesson(
        env.maker,
        w,
        starts_at=local(DAY, 13, 20),
        ends_at=local(DAY, 14, 5),
    )

    first = await env.services.lesson_reminders.execute()
    env.clock.advance(minutes=1)
    second = await env.services.lesson_reminders.execute()

    assert first == {"resources": 0, "prompts": 1}
    assert second == {"resources": 0, "prompts": 0}
    draft = env.outbox.notifications[0]
    assert draft.type is NotificationType.LESSON_PROMPT
    assert draft.user_id == w.teacher.id
    assert draft.dedupe_key == (
        f"prompt:{lesson_id}:{w.teacher.id}:{local(DAY, 14, 5).isoformat()}"
    )
    assert draft.payload == {
        "lesson_id": str(lesson_id),
        "teacher_id": str(w.teacher.id),
        "ends_at": local(DAY, 14, 5).isoformat(),
    }


async def test_prompt_respects_the_teacher_setting_and_missing_teacher(
    env: Env,
) -> None:
    """STF-10, ACA-7: prompts can be off; lessons needing a teacher send none."""
    w = env.world
    env.identity.set_preferences(w.teacher.id, lessons_prompt_enabled=False)
    await add_lesson(
        env.maker, w, starts_at=local(DAY, 13, 20), ends_at=local(DAY, 14, 5)
    )
    await add_lesson(
        env.maker,
        w,
        period=2,
        starts_at=local(DAY, 13, 20),
        ends_at=local(DAY, 14, 5),
        teacher_id=None,
        room_id=None,
    )

    result = await env.services.lesson_reminders.execute()

    assert result == {"resources": 0, "prompts": 0}
