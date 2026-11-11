"""Homework submissions: the rules, the student's and the teacher's use cases."""

import datetime as dt
from uuid import UUID, uuid4

from app.modules.academic.domain.classwork.errors import (
    HomeworkNotFoundError,
    LessonNotFoundError,
    NotLessonTeacherError,
    SubmissionCommentTooLongError,
    SubmissionFilesError,
    SubmissionNotFoundError,
)
from app.modules.academic.domain.classwork.submission_rules import (
    check_submission_files,
    clean_comment,
    submission_status,
)
from app.shared.contracts.files import FileRef
from tests.academic.classwork.conftest import Env
from tests.academic.classwork.world import add_lesson, local

import pytest

FRIDAY = dt.date(2026, 10, 9)
MONDAY = dt.date(2026, 10, 12)


def _ref(owner: UUID, status: str = "ready") -> FileRef:
    return FileRef(
        id=uuid4(),
        owner_id=owner,
        scope="user",  # type: ignore[arg-type]
        purpose="document",  # type: ignore[arg-type]
        name="a.pdf",
        content_type="application/pdf",
        byte_size=1,
        status=status,
        text_bytes=None,
    )


def test_rules_accept_own_ready_files() -> None:
    owner = uuid4()
    ref = _ref(owner)
    check_submission_files([ref.id], {ref.id: ref}, owner)


@pytest.mark.parametrize("status,owned", [("pending", True), ("ready", False)])
def test_rules_refuse_foreign_or_not_ready(status: str, owned: bool) -> None:
    owner = uuid4()
    ref = _ref(owner if owned else uuid4(), status)
    with pytest.raises(SubmissionFilesError):
        check_submission_files([ref.id], {ref.id: ref}, owner)


def test_rules_refuse_missing_and_bad_counts() -> None:
    owner = uuid4()
    with pytest.raises(SubmissionFilesError):
        check_submission_files([], {}, owner)
    with pytest.raises(SubmissionFilesError):
        check_submission_files([uuid4()], {}, owner)
    ids = [uuid4() for _ in range(11)]
    with pytest.raises(SubmissionFilesError):
        check_submission_files(ids, {}, owner)


def test_comment_is_trimmed_and_capped() -> None:
    assert clean_comment("  hi ") == "hi"
    assert clean_comment("  ") is None
    with pytest.raises(SubmissionCommentTooLongError):
        clean_comment("x" * 2001)


def test_status_is_late_after_the_due_day() -> None:
    at = dt.datetime(2026, 10, 12, 10, tzinfo=dt.UTC)
    assert submission_status(None, MONDAY) == "missing"
    assert submission_status(at, MONDAY) == "submitted"
    assert submission_status(at, FRIDAY) == "late"
    assert submission_status(at, None) == "submitted"


async def _lesson(env: Env, due: dt.date | None = MONDAY) -> UUID:
    env.clock.set(local(FRIDAY, 12))
    return await add_lesson(
        env.maker,
        env.world,
        day=FRIDAY,
        period=1,
        homework_text="read",
        homework_due_date=due,
        homework_due_auto=False,
    )


async def test_submit_replace_and_withdraw(env: Env) -> None:
    lesson = await _lesson(env)
    aziz = env.student("aziz")
    first = env.files.add(aziz.user_id)
    second = env.files.add(aziz.user_id)

    view = await env.services.submit_homework.execute(lesson, aziz, [first], " ok ")
    assert view["status"] == "submitted" and view["comment"] == "ok"
    again = await env.services.submit_homework.execute(lesson, aziz, [second], None)
    assert [f["id"] for f in again["files"]] == [str(second)]
    got = await env.services.get_homework_submission.execute(lesson, aziz)
    assert got["comment"] is None

    await env.services.withdraw_homework_submission.execute(lesson, aziz)
    with pytest.raises(SubmissionNotFoundError):
        await env.services.get_homework_submission.execute(lesson, aziz)


async def test_submit_after_due_date_is_late(env: Env) -> None:
    lesson = await _lesson(env, due=FRIDAY - dt.timedelta(days=1))
    aziz = env.student("aziz")
    view = await env.services.submit_homework.execute(
        lesson, aziz, [env.files.add(aziz.user_id)], None
    )
    assert view["status"] == "late"


async def test_submit_refusals(env: Env) -> None:
    lesson = await _lesson(env)
    aziz = env.student("aziz")
    bobur = env.student("bobur")
    with pytest.raises(SubmissionFilesError):
        await env.services.submit_homework.execute(
            lesson, aziz, [env.files.add(bobur.user_id)], None
        )
    with pytest.raises(SubmissionFilesError):
        await env.services.submit_homework.execute(
            lesson, aziz, [env.files.add(aziz.user_id, status="pending")], None
        )
    outsider = env.student("outsider")
    with pytest.raises(LessonNotFoundError):
        await env.services.submit_homework.execute(
            lesson, outsider, [env.files.add(outsider.user_id)], None
        )
    bare = await add_lesson(env.maker, env.world, day=FRIDAY, period=2)
    with pytest.raises(HomeworkNotFoundError):
        await env.services.submit_homework.execute(
            bare, aziz, [env.files.add(aziz.user_id)], None
        )


async def test_teacher_list_counts_and_links(env: Env) -> None:
    lesson = await _lesson(env)
    aziz = env.student("aziz")
    await env.services.submit_homework.execute(
        lesson, aziz, [env.files.add(aziz.user_id)], None
    )

    result = await env.services.list_homework_submissions.execute(lesson, env.teacher)

    assert result["counts"]["submitted"] == 1
    assert result["counts"]["missing"] == result["counts"]["total"] - 1
    done = [s for s in result["students"] if s["status"] == "submitted"]
    assert done[0]["files"][0]["download_url"].startswith("https://files.test/")
    lesson_view = await env.services.staff_lesson.execute(lesson, env.teacher)
    assert lesson_view["homework"]["submissions"]["submitted"] == 1


async def test_teacher_list_is_for_the_lesson_teacher(env: Env) -> None:
    lesson = await _lesson(env)
    with pytest.raises(NotLessonTeacherError):
        await env.services.list_homework_submissions.execute(lesson, env.other_teacher)
