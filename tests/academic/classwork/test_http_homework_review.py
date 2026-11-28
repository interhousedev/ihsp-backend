"""HTTP routes of homework review, settings, switches and the board."""

import datetime as dt
from uuid import UUID

from tests.academic.classwork.conftest import Env
from tests.academic.classwork.test_http import client_as
from tests.academic.classwork.world import DAY, add_lesson
from tests.conftest import HttpClientFactory


async def _lesson(env: Env) -> UUID:
    return await add_lesson(
        env.maker,
        env.world,
        homework_text="Read page 5",
        homework_due_date=DAY + dt.timedelta(days=1),
        homework_due_auto=False,
    )


async def test_switch_submit_review_and_student_sees_the_grade(
    env: Env, http_client: HttpClientFactory
) -> None:
    """Teacher opens submissions, student submits text, teacher grades it."""
    lesson_id = await _lesson(env)
    teacher = await client_as(http_client, env, env.teacher)
    student = await client_as(http_client, env, env.student("aziz"))
    url = f"/v1/me/homework/{lesson_id}/submission"

    closed = await student.put(url, json={"text": "My answer"})
    switched = await teacher.patch(
        f"/v1/staff/lessons/{lesson_id}/homework/settings",
        json={"accept_submissions": True, "notify": False},
    )
    empty = await student.put(url, json={"text": "  "})
    put = await student.put(url, json={"text": "My answer"})
    sid = put.json()
    listed = await teacher.get(f"/v1/staff/lessons/{lesson_id}/homework/submissions")
    row = next(r for r in listed.json()["students"] if r["id"])
    detail = await teacher.get(f"/v1/staff/homework/submissions/{row['id']}")
    no_comment = await teacher.put(
        f"/v1/staff/homework/submissions/{row['id']}/review",
        json={"action": "return"},
    )
    bad_grade = await teacher.put(
        f"/v1/staff/homework/submissions/{row['id']}/review",
        json={"action": "grade", "grade": 7},
    )
    graded = await teacher.put(
        f"/v1/staff/homework/submissions/{row['id']}/review",
        json={"action": "grade", "grade": 5, "comment": "Good"},
    )
    seen = await student.get(url)
    locked = await student.put(url, json={"text": "Changed"})

    assert closed.status_code == 409
    assert closed.json()["type"] == "homework/submissions-closed"
    assert switched.status_code == 200
    homework = switched.json()["homework"]
    assert homework["accept_submissions"] is True
    assert homework["notify"] is False and homework["notify_effective"] is False
    assert empty.status_code == 422
    assert put.status_code == 200 and sid["text"] == "My answer"
    assert sid["review_status"] == "pending"
    assert listed.json()["counts"]["to_review"] == 1
    assert detail.status_code == 200 and detail.json()["text"] == "My answer"
    assert no_comment.status_code == 422
    assert no_comment.json()["type"] == "homework/review-comment-required"
    assert bad_grade.status_code == 422
    assert graded.status_code == 200 and graded.json()["review_status"] == "graded"
    assert seen.json()["grade"] == 5 and seen.json()["teacher_comment"] == "Good"
    assert seen.json()["reviewer"]["id"] == str(env.world.teacher.id)
    assert locked.status_code == 409
    assert locked.json()["type"] == "homework/submission-already-graded"


async def test_notify_null_follows_the_teacher_again(
    env: Env, http_client: HttpClientFactory
) -> None:
    """PATCH with ``notify: null`` resets the override; an omitted field is kept."""
    lesson_id = await _lesson(env)
    teacher = await client_as(http_client, env, env.teacher)
    url = f"/v1/staff/lessons/{lesson_id}/homework/settings"

    await teacher.patch(url, json={"notify": False})
    kept = await teacher.patch(url, json={"accept_submissions": True})
    reset = await teacher.patch(url, json={"notify": None})

    assert kept.json()["homework"]["notify"] is False
    assert reset.json()["homework"]["notify"] is None
    assert reset.json()["homework"]["accept_submissions"] is True


async def test_other_teacher_gets_403_and_other_student_404(
    env: Env, http_client: HttpClientFactory
) -> None:
    """IDOR: the submission id alone gives no access."""
    lesson_id = await _lesson(env)
    teacher = await client_as(http_client, env, env.teacher)
    await teacher.patch(
        f"/v1/staff/lessons/{lesson_id}/homework/settings",
        json={"accept_submissions": True},
    )
    student = await client_as(http_client, env, env.student("aziz"))
    await student.put(f"/v1/me/homework/{lesson_id}/submission", json={"text": "A"})
    listed = await teacher.get(f"/v1/staff/lessons/{lesson_id}/homework/submissions")
    sid = next(r["id"] for r in listed.json()["students"] if r["id"])
    other = await client_as(http_client, env, env.other_teacher)
    outsider = await client_as(http_client, env, env.student("outsider"))

    detail = await other.get(f"/v1/staff/homework/submissions/{sid}")
    review = await other.put(
        f"/v1/staff/homework/submissions/{sid}/review",
        json={"action": "grade", "grade": 4},
    )
    clear = await other.delete(f"/v1/staff/homework/submissions/{sid}/review")
    switches = await other.patch(
        f"/v1/staff/lessons/{lesson_id}/homework/settings",
        json={"accept_submissions": False},
    )
    foreign = await outsider.put(
        f"/v1/me/homework/{lesson_id}/submission", json={"text": "B"}
    )
    missing = await teacher.get(
        "/v1/staff/homework/submissions/00000000-0000-7000-8000-000000000000"
    )

    assert detail.status_code == 403
    assert review.status_code == 403
    assert clear.status_code == 403
    assert switches.status_code == 403
    assert foreign.status_code == 404
    assert missing.status_code == 404


async def test_clear_review_returns_the_work_to_pending(
    env: Env, http_client: HttpClientFactory
) -> None:
    """DELETE .../review gives 204 and the row is pending again."""
    lesson_id = await _lesson(env)
    teacher = await client_as(http_client, env, env.teacher)
    await teacher.patch(
        f"/v1/staff/lessons/{lesson_id}/homework/settings",
        json={"accept_submissions": True},
    )
    student = await client_as(http_client, env, env.student("aziz"))
    await student.put(f"/v1/me/homework/{lesson_id}/submission", json={"text": "A"})
    listed = await teacher.get(f"/v1/staff/lessons/{lesson_id}/homework/submissions")
    sid = next(r["id"] for r in listed.json()["students"] if r["id"])
    review_url = f"/v1/staff/homework/submissions/{sid}/review"
    await teacher.put(review_url, json={"action": "return", "comment": "Redo"})

    cleared = await teacher.delete(review_url)
    row = await teacher.get(f"/v1/staff/homework/submissions/{sid}")

    assert cleared.status_code == 204
    assert row.json()["review_status"] == "pending"
    assert row.json()["grade"] is None


async def test_settings_get_and_put(env: Env, http_client: HttpClientFactory) -> None:
    """The teacher's own defaults; an omitted field is kept."""
    teacher = await client_as(http_client, env, env.teacher)

    before = await teacher.get("/v1/staff/homework/settings")
    saved = await teacher.put(
        "/v1/staff/homework/settings", json={"accept_by_default": True}
    )
    after = await teacher.get("/v1/staff/homework/settings")

    assert before.json() == {"accept_by_default": False, "notify_on_submission": True}
    assert saved.json() == {"accept_by_default": True, "notify_on_submission": True}
    assert after.json() == saved.json()


async def test_homework_board(env: Env, http_client: HttpClientFactory) -> None:
    """GET /v1/staff/homework lists the option's lessons; a foreign option is 404."""
    lesson_id = await _lesson(env)
    teacher = await client_as(http_client, env, env.teacher)
    option = (await teacher.get("/v1/staff/journal/options")).json()[0]
    params = {
        "subject_id": option["subject"]["id"],
        "audience_key": option["audience_key"],
        "only": "with_homework",
    }

    board = await teacher.get("/v1/staff/homework", params=params)
    other = await client_as(http_client, env, env.other_teacher)
    foreign = await other.get("/v1/staff/homework", params=params)

    assert board.status_code == 200
    item = next(i for i in board.json()["lessons"] if i["lesson_id"] == str(lesson_id))
    assert item["homework"]["source"] == "teacher"
    assert item["counts"]["total"] == 3
    assert foreign.status_code == 404
