"""Coach HTTP routes and the Duo bug regressions visible over HTTP (spec 2.2, 2.4).

The implementation must provide the routes (all under /v1/lms):
  POST /steps/{step_id}/coach/sessions            body {block_id?, trigger} -> 201/200
  {id, mode, hint_level}
  POST /coach/sessions/{id}/turns                 body {message} -> {message,
  hint_level, ask_back}
  POST /coach/sessions/{id}/close                 body {outcome}
  GET  /steps/{step_id}/coach/sessions?latest=1
  GET|PUT /courses/{id}/steps/{step_id}/solution-keys   (staff EDIT)
  GET  /courses/{id}/coach/insights?from&to             (staff REVIEW)
and, for B3 / B2:
  outline step view gains `lock_reason: "audience"|"mastery"|null`; `locked` is true
  for mastery locks (wiring: build_learning(..., locked_step_ids=...)).
  The enrol response carries `enrolled_via` and `continue_step_id`.
Until implemented these fail with 404 / missing keys, as expected in TDD.
"""

from uuid import uuid4

from app.modules.lms.application.engagement.service import EngagementService
from app.modules.lms.application.engagement.views import EngagementSettingsView
from app.modules.lms.infrastructure.orm.enrollment import Enrollment
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from tests.lms.learning.builders import SeededCourse, add_staff
from tests.lms.learning.http.test_lms_learning_http import course_with_everything
from tests.lms.learning.integration.test_engagement_lock import (  # noqa: F401
    _two_sections,
    engagement,
    locked_learning,
)
from tests.lms.learning.scenarios import WRONG, quiz_course, take

from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Permission mapping (spec 2.4): solution keys need course staff "edit"; insights need
# course staff "review" (the existing permission; VIEW_STUDENTS does not exist).


async def _enrolled_session(
    client: AsyncClient, caller: dict[str, Actor], student: Actor, course: SeededCourse
) -> str:
    caller["actor"] = student
    assert (await client.post(f"/v1/lms/courses/{course.id}/enroll")).status_code == 200
    r = await client.post(
        f"/v1/lms/steps/{course.step('quiz').step_id}/coach/sessions",
        json={"trigger": "learner_tap"},
    )
    assert r.status_code in (200, 201)
    return str(r.json()["id"])


async def test_unenrolled_student_cannot_open_a_session(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    course = await course_with_everything(maker)
    caller["actor"] = student
    r = await client.post(
        f"/v1/lms/steps/{course.step('quiz').step_id}/coach/sessions",
        json={"trigger": "learner_tap"},
    )
    assert r.status_code == 403
    assert r.json()["type"] != "about:blank"


async def test_another_student_cannot_read_turn_or_close_a_session(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    other_student: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """IDOR over real HTTP: the session exists, but belongs to `student`."""
    course = await course_with_everything(maker)
    sid = await _enrolled_session(client, caller, student, course)
    caller["actor"] = other_student
    assert (await client.post(f"/v1/lms/courses/{course.id}/enroll")).status_code == 200
    turn = await client.post(
        f"/v1/lms/coach/sessions/{sid}/turns", json={"message": "hi"}
    )
    close = await client.post(
        f"/v1/lms/coach/sessions/{sid}/close", json={"outcome": "resolved"}
    )
    latest = await client.get(
        f"/v1/lms/steps/{course.step('quiz').step_id}/coach/sessions",
        params={"latest": 1},
    )
    assert turn.status_code == close.status_code == 404
    assert sid not in latest.text
    caller["actor"] = student
    own = await client.post(
        f"/v1/lms/coach/sessions/{sid}/close", json={"outcome": "abandoned"}
    )
    assert own.status_code == 200


async def test_withdrawn_enrolment_stops_the_session(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    course = await course_with_everything(maker)
    sid = await _enrolled_session(client, caller, student, course)
    async with maker() as db:  # no withdraw route: the staff action removes the row
        await db.execute(
            delete(Enrollment).where(Enrollment.user_id == student.user_id)
        )
        await db.commit()
    r = await client.post(f"/v1/lms/coach/sessions/{sid}/turns", json={"message": "hi"})
    assert r.status_code == 403


async def test_solution_keys_need_edit_on_that_very_course(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    teacher: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    mine = await course_with_everything(maker)
    other = await course_with_everything(maker, slug="geometry")
    url = f"/v1/lms/courses/{mine.id}/steps/{mine.step('quiz').step_id}/solution-keys"
    caller["actor"] = student
    assert (await client.get(url)).status_code == 403
    caller["actor"] = teacher  # not staff anywhere
    assert (await client.get(url)).status_code == 403
    await add_staff(
        maker, other, teacher.user_id, permissions=["edit"]
    )  # edit on ANOTHER course
    assert (await client.get(url)).status_code == 403
    await add_staff(
        maker, mine, teacher.user_id, permissions=["review"]
    )  # wrong permission
    assert (await client.get(url)).status_code == 403
    assert (await client.put(url, json={"keys": []})).status_code == 403


async def test_solution_keys_are_served_to_course_editors(
    client: AsyncClient,
    caller: dict[str, Actor],
    teacher: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    course = await course_with_everything(maker)
    await add_staff(maker, course, teacher.user_id, permissions=["edit"])
    caller["actor"] = teacher
    url = (
        f"/v1/lms/courses/{course.id}/steps/{course.step('quiz').step_id}/solution-keys"
    )
    assert (await client.get(url)).status_code == 200


async def test_insights_need_review_on_that_very_course(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    teacher: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    course = await course_with_everything(maker)
    url = f"/v1/lms/courses/{course.id}/coach/insights"
    caller["actor"] = student
    assert (await client.get(url)).status_code == 403
    caller["actor"] = teacher
    assert (await client.get(url)).status_code == 403  # not staff
    await add_staff(maker, course, teacher.user_id, permissions=["edit"])
    assert (await client.get(url)).status_code == 403  # edit is not review
    assert (await client.get(url)).json()["type"] != "about:blank"


async def test_insights_are_served_to_reviewing_staff(
    client: AsyncClient,
    caller: dict[str, Actor],
    teacher: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    course = await course_with_everything(maker)
    await add_staff(maker, course, teacher.user_id, permissions=["review"])
    caller["actor"] = teacher
    assert (
        await client.get(f"/v1/lms/courses/{course.id}/coach/insights")
    ).status_code == 200


async def test_unknown_step_is_a_problem_json_404(
    client: AsyncClient, caller: dict[str, Actor], student: Actor
) -> None:
    caller["actor"] = student
    r = await client.post(
        f"/v1/lms/steps/{uuid4()}/coach/sessions", json={"trigger": "learner_tap"}
    )
    assert r.status_code == 404 and r.json()["type"] != "about:blank"


# ---- B3: the outline marks mastery-locked steps as locked ---------------------


async def test_course_page_locks_mastery_locked_steps(
    maker: async_sessionmaker[AsyncSession],
    locked_learning: LearningServices,  # noqa: F811
    engagement: EngagementService,  # noqa: F811
    student: Actor,
    teacher: Actor,
) -> None:
    """B3: section 2 is locked with lock_reason 'mastery' until section 1 passes."""
    course, quiz = await quiz_course(
        maker, locked_learning, student, with_text_step=True
    )
    await _two_sections(maker, course)
    await add_staff(maker, course, teacher.user_id, permissions=["review", "edit"])
    await engagement.set_settings(
        teacher, course.id, EngagementSettingsView(unlock_threshold_pct=80)
    )
    await take(locked_learning, student, quiz, WRONG)
    page = await locked_learning.get_course_page.execute(student, course.slug)
    steps = {s.step_id: s for sec in page.outline for s in sec.steps}
    text = steps[course.step("text").step_id]
    assert text.locked is True
    assert text.lock_reason == "mastery"
    assert steps[quiz.step_id].locked is False
    assert steps[quiz.step_id].lock_reason is None


# ---- B2: enrolling by id or by slug returns the same course -------------------


async def test_enrol_by_id_and_page_by_slug_agree(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    course = await course_with_everything(maker)
    caller["actor"] = student
    by_id = await client.post(f"/v1/lms/courses/{course.id}/enroll")
    by_slug = await client.get(f"/v1/lms/courses/{course.slug}")
    by_id_get = await client.get(f"/v1/lms/courses/{course.id}")
    assert by_id.status_code == 200
    assert by_id.json()["enrolled"] is True
    assert by_id_get.json() == by_slug.json()
    assert "continue_step_id" in by_id.json() and "enrolled_via" in by_id.json()


async def test_enrol_by_slug_returns_the_same_course(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The enrol route also accepts the slug and is idempotent."""
    course = await course_with_everything(maker)
    caller["actor"] = student
    a = await client.post(f"/v1/lms/courses/{course.slug}/enroll")
    b = await client.post(f"/v1/lms/courses/{course.id}/enroll")
    assert a.status_code == b.status_code == 200
    assert a.json()["id"] == b.json()["id"] == str(course.id)
