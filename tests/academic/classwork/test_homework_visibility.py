"""ACA-10, STF-7, WEB-3, WEB-18, UF-STF-05, BOT-18: homework reaches the to-do list.

A teacher adds homework through the staff portal or the bot (``due_date=None``) and
every student of the lesson's audience finds it in the to-do list and on Today, even
when it is already past due.
"""

import datetime as dt
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.me_classwork import ROUTERS as ME_ROUTERS
from app.interfaces.http.v1.staff_classwork import ROUTERS as STAFF_ROUTERS
from app.modules.academic.domain.classwork.errors import HomeworkCancelledLessonError
from app.shared.actor import Actor
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import DAY, add_lesson, lesson_row, local
from tests.conftest import HttpClientFactory

import pytest
from httpx import AsyncClient

Channel = Literal["staff", "bot"]
CHANNELS: list[Channel] = ["staff", "bot"]
STATUSES = ("overdue", "upcoming", "later", "done")

DAY_1 = dt.timedelta(days=1)
WEDNESDAY = DAY + DAY_1
FRIDAY = DAY + 3 * DAY_1
FRIDAY_BEFORE = DAY - 4 * DAY_1
MONDAY_BEFORE = DAY - DAY_1


async def _client(
    http_client: HttpClientFactory, env: Env, actor: Actor
) -> AsyncClient:
    return await http_client(
        [*ME_ROUTERS, *STAFF_ROUTERS],
        overrides={get_actor: lambda: actor},
        academic=SimpleNamespace(classwork=env.services),
    )


async def _teacher_adds(
    env: Env,
    http_client: HttpClientFactory,
    channel: Channel,
    lesson_id: UUID,
    text: str,
    due: dt.date | None = None,
) -> None:
    """Add homework the way the teacher does: the staff portal or the bot."""
    if channel == "bot":
        await env.services.commands.set_homework(lesson_id, env.teacher, text, due)
        return
    client = await _client(http_client, env, env.teacher)
    body: dict[str, Any] = {"text": text}
    if due is not None:
        body["due_date"] = due.isoformat()
    response = await client.put(f"/v1/staff/lessons/{lesson_id}/homework", json=body)
    assert response.status_code == 200, response.text


async def _lists(
    env: Env, http_client: HttpClientFactory, who: str
) -> dict[str, list[dict[str, Any]]]:
    """Every to-do list of a student as ``GET /v1/me/homework`` serves it."""
    client = await _client(http_client, env, env.student(who))
    lists = {}
    for status in STATUSES:
        response = await client.get("/v1/me/homework", params={"status": status})
        assert response.status_code == 200, response.text
        lists[status] = response.json()
    return lists


def _where(lists: dict[str, list[dict[str, Any]]], text: str) -> list[str]:
    """The names of the lists that contain the homework."""
    return [
        status
        for status, items in lists.items()
        if any(item["text"] == text for item in items)
    ]


async def _today_due(
    env: Env, http_client: HttpClientFactory, who: str
) -> list[dict[str, Any]]:
    client = await _client(http_client, env, env.student(who))
    response = await client.get("/v1/me/today")
    assert response.status_code == 200, response.text
    due: list[dict[str, Any]] = response.json()["due"]
    return due


async def _tuesday_physics(env: Env, audience: list[str] | None = None) -> UUID:
    """Tuesday physics; Wednesday maths is the next study day, Friday is physics."""
    w = env.world
    given = await add_lesson(env.maker, w, day=DAY, audience=audience)
    await add_lesson(env.maker, w, day=WEDNESDAY, subject_id=w.math_id)
    await add_lesson(env.maker, w, day=FRIDAY, audience=audience)
    return given


async def _late_homework_world(env: Env) -> UUID:
    """Friday physics, next physics on Monday, and both are over by now (Tuesday)."""
    w = env.world
    given = await add_lesson(env.maker, w, day=FRIDAY_BEFORE)
    await add_lesson(env.maker, w, day=MONDAY_BEFORE)
    await add_lesson(env.maker, w, day=WEDNESDAY, subject_id=w.math_id)
    return given


# - - - Homework reaches the whole audience - - -


@pytest.mark.parametrize("channel", CHANNELS)
@pytest.mark.parametrize("who", ["aziz", "bobur", "camila"])
async def test_homework_for_the_whole_group_is_in_every_students_todo(
    env: Env, http_client: HttpClientFactory, channel: Channel, who: str
) -> None:
    """ACA-10, UF-STF-05 3: group students, with or without a subgroup, see it."""
    given = await _tuesday_physics(env)

    await _teacher_adds(env, http_client, channel, given, "Read page 5")

    lists = await _lists(env, http_client, who)
    assert _where(lists, "Read page 5") == ["later"]  # due Friday, after Wednesday
    item = lists["later"][0]
    assert item["due_date"] == FRIDAY.isoformat()
    assert item["days_overdue"] == 0


@pytest.mark.parametrize("channel", CHANNELS)
async def test_homework_due_on_the_next_study_day_is_upcoming_and_on_today(
    env: Env, http_client: HttpClientFactory, channel: Channel
) -> None:
    """WEB-3, WEB-18: due Wednesday, the next study day."""
    given = await _tuesday_physics(env)

    await _teacher_adds(env, http_client, channel, given, "For tomorrow", WEDNESDAY)

    lists = await _lists(env, http_client, "aziz")
    assert _where(lists, "For tomorrow") == ["upcoming"]
    assert [item["text"] for item in await _today_due(env, http_client, "aziz")] == [
        "For tomorrow"
    ]


@pytest.mark.parametrize("channel", CHANNELS)
@pytest.mark.parametrize(
    ("who", "sees"),
    [("aziz", True), ("camila", True), ("bobur", False), ("outsider", False)],
)
async def test_subgroup_homework_reaches_that_subgroup_and_unassigned_students(
    env: Env, http_client: HttpClientFactory, channel: Channel, who: str, sees: bool
) -> None:
    """ACA-2, ACA-10: subgroup homework; students without a subgroup see it too."""
    audience = [f"{env.world.group_id}:1"]
    given = await _tuesday_physics(env, audience)

    await _teacher_adds(env, http_client, channel, given, "Subgroup task")

    lists = await _lists(env, http_client, who)
    assert (_where(lists, "Subgroup task") == ["later"]) is sees
    if sees:
        assert lists["later"][0]["due_date"] == FRIDAY.isoformat()


@pytest.mark.parametrize("channel", CHANNELS)
async def test_homework_with_no_next_lesson_is_listed_without_a_due_date(
    env: Env, http_client: HttpClientFactory, channel: Channel
) -> None:
    """UF-STF-05 2a: end of term, no due date; the student still sees it."""
    given = await add_lesson(env.maker, env.world, day=DAY)

    await _teacher_adds(env, http_client, channel, given, "Last task")

    lists = await _lists(env, http_client, "aziz")
    assert _where(lists, "Last task") == ["later"]
    assert lists["later"][0]["due_date"] is None


# - - - Past due - - -


@pytest.mark.parametrize("channel", CHANNELS)
@pytest.mark.parametrize("who", ["aziz", "bobur", "camila"])
async def test_homework_added_after_the_next_lesson_is_overdue_not_lost(
    env: Env, http_client: HttpClientFactory, channel: Channel, who: str
) -> None:
    """ACA-10, WEB-18: past due items are listed in Overdue."""
    given = await _late_homework_world(env)

    await _teacher_adds(env, http_client, channel, given, "Late task")

    lists = await _lists(env, http_client, who)
    assert _where(lists, "Late task") == ["overdue"]
    assert lists["overdue"][0]["due_date"] == MONDAY_BEFORE.isoformat()
    assert lists["overdue"][0]["days_overdue"] == 1


async def test_overdue_lists_the_most_overdue_first(
    env: Env, http_client: HttpClientFactory
) -> None:
    """WEB-18: the oldest due date comes first."""
    w = env.world
    for days, text in ((1, "one day"), (5, "five days"), (3, "three days")):
        await add_lesson(
            env.maker,
            w,
            day=DAY - 6 * DAY_1,
            period=days,
            homework_text=text,
            homework_due_date=DAY - days * DAY_1,
            homework_due_auto=False,
        )

    lists = await _lists(env, http_client, "aziz")

    assert [item["text"] for item in lists["overdue"]] == [
        "five days",
        "three days",
        "one day",
    ]
    assert [item["days_overdue"] for item in lists["overdue"]] == [5, 3, 1]


async def test_a_lesson_far_in_the_past_still_lists_its_open_homework(
    env: Env, http_client: HttpClientFactory
) -> None:
    """WEB-18: open homework stays until it is done or removed."""
    await add_lesson(
        env.maker,
        env.world,
        day=DAY - 40 * DAY_1,
        homework_text="Old task",
        homework_due_date=DAY - 38 * DAY_1,
        homework_due_auto=False,
    )

    lists = await _lists(env, http_client, "aziz")

    assert _where(lists, "Old task") == ["overdue"]
    assert lists["overdue"][0]["days_overdue"] == 38


async def test_overdue_homework_counts_on_today_and_comes_first(
    env: Env, http_client: HttpClientFactory
) -> None:
    """WEB-3: Today lists the overdue items before the ones due next study day."""
    given = await _late_homework_world(env)
    await env.services.set_homework.execute(given, env.teacher, "Late task", None)
    fresh = await add_lesson(env.maker, env.world, day=DAY, period=2)
    await env.services.set_homework.execute(fresh, env.teacher, "Fresh", WEDNESDAY)

    due = await _today_due(env, http_client, "aziz")

    assert [(item["text"], item["days_overdue"]) for item in due] == [
        ("Late task", 1),
        ("Fresh", 0),
    ]


async def test_done_items_are_not_overdue(
    env: Env, http_client: HttpClientFactory
) -> None:
    """WEB-19: ticking an overdue item moves it to Done; unticking brings it back."""
    given = await _late_homework_world(env)
    await env.services.set_homework.execute(given, env.teacher, "Late task", None)
    client = await _client(http_client, env, env.student("aziz"))

    ticked = await client.put(f"/v1/me/homework/{given}/done", json={"done": True})
    lists = await _lists(env, http_client, "aziz")
    untick = await client.put(f"/v1/me/homework/{given}/done", json={"done": False})
    back = await _lists(env, http_client, "aziz")

    assert ticked.json()["done_at"] is not None
    assert ticked.json()["days_overdue"] == 0
    assert _where(lists, "Late task") == ["done"]
    assert untick.json()["days_overdue"] == 1
    assert _where(back, "Late task") == ["overdue"]


async def test_overdue_follows_the_tashkent_date_not_the_utc_date(
    env: Env, http_client: HttpClientFactory
) -> None:
    """Asia/Tashkent: at 01:30 on Wednesday (still Tuesday in UTC) Tuesday is past."""
    env.clock.set(local(WEDNESDAY, 1, 30))
    due_tuesday = await add_lesson(
        env.maker, env.world, day=DAY - DAY_1, homework_text="Tuesday"
    )
    due_wednesday = await add_lesson(
        env.maker, env.world, day=DAY - DAY_1, period=2, homework_text="Wednesday"
    )
    await env.services.set_homework.execute(due_tuesday, env.teacher, "Tuesday", DAY)
    await env.services.set_homework.execute(
        due_wednesday, env.teacher, "Wednesday", WEDNESDAY
    )

    lists = await _lists(env, http_client, "aziz")

    assert _where(lists, "Tuesday") == ["overdue"]
    assert lists["overdue"][0]["days_overdue"] == 1
    assert _where(lists, "Wednesday") == ["upcoming"]


async def test_homework_of_a_cancelled_lesson_is_not_assigned(
    env: Env, http_client: HttpClientFactory
) -> None:
    """The lesson did not take place, so the task is not shown."""
    await add_lesson(
        env.maker,
        env.world,
        day=DAY,
        status="cancelled",
        homework_text="Cancelled",
        homework_due_date=WEDNESDAY,
    )

    lists = await _lists(env, http_client, "aziz")

    assert _where(lists, "Cancelled") == []


async def test_homework_cannot_be_set_on_a_cancelled_lesson(
    env: Env, http_client: HttpClientFactory
) -> None:
    """ACA-10: refused, not saved where no student would ever see it."""
    cancelled = await add_lesson(env.maker, env.world, day=DAY, status="cancelled")
    client = await _client(http_client, env, env.teacher)

    over_http = await client.put(
        f"/v1/staff/lessons/{cancelled}/homework", json={"text": "Never seen"}
    )
    with pytest.raises(HomeworkCancelledLessonError):
        await env.services.commands.set_homework(
            cancelled, env.teacher, "Never seen", None
        )

    assert over_http.status_code == 422
    assert over_http.json()["type"] == "homework/lesson-cancelled"
    row = await lesson_row(env.maker, cancelled)
    assert row.homework_text is None


# - - - Staff portal and the bot's own list - - -


@pytest.mark.parametrize("channel", CHANNELS)
async def test_the_staff_portal_still_shows_what_the_teacher_added(
    env: Env, http_client: HttpClientFactory, channel: Channel
) -> None:
    """STF-7: the lesson page keeps the text, the due date and the auto flag."""
    given = await _late_homework_world(env)

    await _teacher_adds(env, http_client, channel, given, "Late task")

    client = await _client(http_client, env, env.teacher)
    page = (await client.get(f"/v1/staff/lessons/{given}")).json()
    assert page["homework"] == {
        "text": "Late task",
        "due_date": MONDAY_BEFORE.isoformat(),
        "due_auto": True,
    }
    assert page["lesson"]["has_homework"] is True


async def test_the_bots_homework_list_includes_overdue_items(env: Env) -> None:
    """BOT-18: ClassworkQueries.homework without a lower bound lists overdue items."""
    given = await _late_homework_world(env)
    await env.services.commands.set_homework(given, env.teacher, "Late task", None)

    items = await env.services.queries.homework(env.world.aziz.id, None, None, False)

    assert [item["lesson"].homework_text for item in items] == ["Late task"]
