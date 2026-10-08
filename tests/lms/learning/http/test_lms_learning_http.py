"""LMS-1 to LMS-20: the learning endpoints of the API contract over HTTP."""

from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from tests.lms.learning.builders import (
    SeededCourse,
    add_preview_revision,
    add_staff,
    cards,
    content,
    quiz,
    seed_course,
    text_block,
)
from tests.lms.learning.fakes.preview_revisions import FakePreviewRevisions
from tests.lms.learning.helpers import FORBIDDEN_KEYS, keys_of
from tests.lms.learning.scenarios import QUESTIONS, RIGHT, WRONG

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PROBLEM = "application/problem+json"


async def course_with_everything(
    maker: async_sessionmaker[AsyncSession], **options: object
) -> SeededCourse:
    """A published course with a text step, a quiz step and a flash card step."""
    return await seed_course(
        maker,
        steps=[
            ("text", content("Reading", text_block())),
            ("quiz", content("Quiz", quiz("quiz", QUESTIONS, max_attempts=2))),
            ("cards", content("Cards", cards())),
        ],
        **options,  # type: ignore[arg-type]
    )


async def test_the_catalog_and_my_courses_follow_the_contract(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """UF-LMS-01: GET /v1/lms/courses, GET /v1/lms/my-courses."""
    course = await course_with_everything(maker)
    caller["actor"] = student

    catalog = await client.get("/v1/lms/courses")
    nothing = await client.get("/v1/lms/courses", params={"query": "zzz"})
    mine = await client.get("/v1/lms/my-courses")

    assert catalog.status_code == 200
    assert catalog.headers["cache-control"] == "private, max-age=60"
    assert catalog.json() == [
        {
            "id": str(course.id),
            "slug": "algebra",
            "title": "Algebra",
            "description": "About Algebra",
            "cover_url": None,
            "steps_count": 3,
            "progress_pct": None,
            "visibility": "public",
            "updated_at": catalog.json()[0]["updated_at"],
        }
    ]
    assert catalog.json()[0]["updated_at"].endswith("Z")
    assert nothing.json() == []
    assert mine.json() == {"enrolled": [], "managed": []}
    assert mine.headers["cache-control"] == "private, no-store"


async def test_enrolling_returns_the_course_page(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    teacher: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """UF-LMS-01: POST /v1/lms/courses/{id}/enroll and GET /v1/lms/courses/{slug}."""
    course = await course_with_everything(maker)
    await add_staff(
        maker, course, teacher.user_id, role="Teacher", permissions=["edit", "review"]
    )
    caller["actor"] = student

    enrolled = await client.post(f"/v1/lms/courses/{course.id}/enroll")
    page = await client.get(f"/v1/lms/courses/{course.slug}")

    assert enrolled.status_code == 200
    assert enrolled.json() == page.json()
    body = page.json()
    assert (body["enrolled"], body["can_edit"], body["progress_pct"]) == (
        True,
        False,
        0,
    )
    assert body["changed_since_last_visit"] == []
    assert body["staff"] == [
        {
            "user": {
                "id": str(teacher.user_id),
                "first_name": "Tim",
                "last_name": "Teacher",
            },
            "role": "Teacher",
            "permissions": ["edit", "review"],
            "show_on_page": True,
            "position": 0,
        }
    ]
    assert body["outline"][0]["steps"][0] == {
        "step_id": str(course.step("text").step_id),
        "title": "Reading",
        "completed": False,
        "badge": None,
    }
    assert page.headers["cache-control"] == "private, max-age=60"


async def test_an_unknown_invite_code_is_a_problem_document(
    client: AsyncClient, caller: dict[str, Actor], student: Actor
) -> None:
    """UF-LMS-02 1a: POST /v1/lms/join with a wrong code -> 404."""
    caller["actor"] = student

    response = await client.post("/v1/lms/join", json={"code": "WRONGCODE1"})

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM)
    assert response.json()["type"] == "lms/invite-not-valid"
    assert response.json()["message_key"] == "lms-learn-invite-not-valid"


async def test_joining_with_the_code_enrolls_and_is_rate_limited(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """UF-LMS-02: join works; the 11th try within an hour is 429 with retry_after."""
    await seed_course(
        maker,
        visibility="invite",
        invite_code="ABCDEFGHJK",
        steps=[("s", content("Only", text_block()))],
    )
    caller["actor"] = student

    joined = await client.post("/v1/lms/join", json={"code": "ABCDEFGHJK"})
    for _ in range(9):
        await client.post("/v1/lms/join", json={"code": "ABCDEFGHJK"})
    limited = await client.post("/v1/lms/join", json={"code": "ABCDEFGHJK"})

    assert joined.status_code == 200
    assert joined.json()["enrolled"] is True
    assert limited.status_code == 429
    assert limited.json()["type"] == "common/rate-limited"
    assert limited.json()["params"]["retry_after"] > 0


async def test_a_step_is_read_and_marked_viewed(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    learning: LearningServices,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """UF-LMS-03: GET .../steps/{step_id}, POST /v1/lms/steps/{step_id}/viewed."""
    course = await course_with_everything(maker)
    await learning.enroll_in_course.execute(student, course.id)
    caller["actor"] = student
    text = course.step("text").step_id
    quiz_step = course.step("quiz").step_id

    step = await client.get(f"/v1/lms/courses/{course.id}/steps/{text}")
    viewed = await client.post(f"/v1/lms/steps/{text}/viewed")
    test_step = await client.get(f"/v1/lms/courses/{course.id}/steps/{quiz_step}")

    assert step.status_code == 200
    assert step.headers["cache-control"] == "private, max-age=60"
    assert step.json() == {
        "step_id": str(text),
        "revision_id": str(course.step("text").revision_id),
        "title": "Reading",
        "blocks": [{"id": "text", "type": "text", "markdown": "Read this."}],
        "completed": False,
        "preview": False,
    }
    assert viewed.json()["completed"] is True
    assert viewed.json()["step_id"] == str(text)
    assert viewed.json()["viewed_at"].endswith("Z")
    assert test_step.json()["blocks"][0] == {
        "id": "quiz",
        "type": "test",
        "rules": {
            "questions": 3,
            "attempts_left": 2,
            "time_limit_sec": None,
            "passing_score_pct": 60.0,
        },
        "best": None,
        "open_attempt_id": None,
    }
    assert not FORBIDDEN_KEYS & keys_of(test_step.json())


async def test_a_student_who_is_not_enrolled_gets_a_403_problem(
    client: AsyncClient,
    caller: dict[str, Actor],
    other_student: Actor,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """LMS-19: steps need enrollment."""
    course = await course_with_everything(maker)
    caller["actor"] = other_student

    response = await client.get(
        f"/v1/lms/courses/{course.id}/steps/{course.step('text').step_id}"
    )

    assert response.status_code == 403
    assert response.json()["type"] == "lms/not-enrolled"


async def test_taking_and_reviewing_a_test_over_http(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    teacher: Actor,
    learning: LearningServices,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """UF-LMS-04, UF-LMS-15: start, save, submit, read, override and list students."""
    course = await course_with_everything(maker)
    await learning.enroll_in_course.execute(student, course.id)
    await add_staff(maker, course, teacher.user_id, permissions=["review"])
    step = course.step("quiz").step_id
    caller["actor"] = student

    started = await client.post(f"/v1/lms/steps/{step}/blocks/quiz/attempts")
    attempt = started.json()
    saved = await client.put(
        f"/v1/lms/attempts/{attempt['id']}/answers", json={"answers": WRONG}
    )
    submitted = await client.post(f"/v1/lms/attempts/{attempt['id']}/submit")
    read = await client.get(f"/v1/lms/attempts/{attempt['id']}")
    caller["actor"] = teacher
    students = await client.get(f"/v1/lms/courses/{course.id}/students")
    overridden = await client.post(
        f"/v1/lms/attempts/{attempt['id']}/override",
        json={"score": 3, "comment": "Accept the spelling."},
    )

    assert started.status_code == 200
    assert set(attempt) == {
        "id",
        "block_id",
        "attempt_no",
        "started_at",
        "deadline_at",
        "questions",
        "answers",
        "submitted_at",
    }
    assert attempt["attempt_no"] == 1
    assert not FORBIDDEN_KEYS & keys_of(attempt)
    assert saved.json()["answers"] == WRONG
    assert submitted.json()["score"] == 0.0
    assert submitted.json()["max_score"] == 3.0
    assert submitted.json()["passed"] is False
    assert [r["question_id"] for r in submitted.json()["review"]] == ["q1", "q2", "q3"]
    assert read.json()["user"] == {
        "id": str(student.user_id),
        "first_name": "Sam",
        "last_name": "Student",
    }
    assert read.json()["revision_id"] == str(course.step("quiz").revision_id)
    assert read.json()["variant"]["question_ids"] == ["q1", "q2", "q3"]
    assert read.json()["override_score"] is None
    assert students.json()[0]["attempts"][0]["id"] == attempt["id"]
    assert students.json()[0]["progress_pct"] == 0
    assert overridden.status_code == 200
    assert overridden.json()["score"] == 3.0
    assert overridden.json()["passed"] is True
    assert overridden.json()["override_comment"] == "Accept the spelling."


async def test_errors_of_attempts_are_problem_documents(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    learning: LearningServices,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """UF-LMS-04: limits, closed attempts and bad bodies map to stable types."""
    course = await course_with_everything(maker)
    await learning.enroll_in_course.execute(student, course.id)
    step = course.step("quiz").step_id
    caller["actor"] = student
    for _ in range(2):
        attempt = (
            await client.post(f"/v1/lms/steps/{step}/blocks/quiz/attempts")
        ).json()
        await client.post(f"/v1/lms/attempts/{attempt['id']}/submit")

    limit = await client.post(f"/v1/lms/steps/{step}/blocks/quiz/attempts")
    closed = await client.put(
        f"/v1/lms/attempts/{attempt['id']}/answers", json={"answers": RIGHT}
    )
    bad_body = await client.put(
        f"/v1/lms/attempts/{attempt['id']}/answers", json={"answers": [1, 2]}
    )
    bad_number = await client.put(
        f"/v1/lms/attempts/{attempt['id']}/answers",
        json={"answers": {"q2": {"number": "five"}}},
    )

    assert (limit.status_code, limit.json()["type"]) == (409, "lms/no-attempts-left")
    assert (closed.status_code, closed.json()["type"]) == (409, "lms/attempt-closed")
    assert (bad_body.status_code, bad_body.json()["type"]) == (
        422,
        "common/request-validation",
    )
    assert bad_number.status_code == 422


async def test_flash_cards_are_studied_over_http(
    client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    learning: LearningServices,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """UF-LMS-03: GET .../cards/next and POST .../cards/{card_id}/review."""
    course = await course_with_everything(maker)
    await learning.enroll_in_course.execute(student, course.id)
    step = course.step("cards").step_id
    caller["actor"] = student

    first = await client.get(
        f"/v1/lms/steps/{step}/cards/next", params={"block_id": "cards"}
    )
    rated = await client.post(
        f"/v1/lms/steps/{step}/cards/c1/review", json={"rating": "medium"}
    )
    bad_rating = await client.post(
        f"/v1/lms/steps/{step}/cards/c1/review", json={"rating": "perfect"}
    )
    no_block = await client.get(f"/v1/lms/steps/{step}/cards/next")

    assert first.json() == {
        "block_id": "cards",
        "card": {"id": "c1", "front": "Front 1", "back": "Back 1"},
        "intervals": {"again": "1m", "hard": "1m", "medium": "10m", "easy": "4d"},
        "counts": {"learning": 0, "review": 0, "new": 3},
    }
    assert rated.json()["card"]["id"] == "c2"
    assert rated.json()["counts"] == {"learning": 0, "review": 0, "new": 2}
    assert bad_rating.status_code == 422
    assert no_block.status_code == 422


async def test_staff_preview_attempts_use_the_preview_flag(
    client: AsyncClient,
    caller: dict[str, Actor],
    teacher: Actor,
    previews: FakePreviewRevisions,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """UF-LMS-09: POST .../attempts?preview=true for staff with view_drafts."""
    course = await course_with_everything(maker)
    step = course.step("quiz")
    await add_staff(maker, course, teacher.user_id, permissions=["view_drafts"])
    draft = content("Quiz", quiz("quiz", [QUESTIONS[1]]))
    previews.revisions[step.step_id] = await add_preview_revision(
        maker, step, draft, teacher.user_id
    )
    caller["actor"] = teacher

    denied = await client.post(f"/v1/lms/steps/{step.step_id}/blocks/quiz/attempts")
    preview = await client.post(
        f"/v1/lms/steps/{step.step_id}/blocks/quiz/attempts", params={"preview": "true"}
    )

    assert (denied.status_code, denied.json()["type"]) == (403, "lms/not-enrolled")
    assert preview.status_code == 200
    assert [q["id"] for q in preview.json()["questions"]] == ["q2"]


async def test_requests_without_a_token_are_unauthorized(
    anonymous_client: AsyncClient,
) -> None:
    """LMS-1: the endpoints need a logged-in user."""
    response = await anonymous_client.get("/v1/lms/courses")

    assert response.status_code == 401
    assert response.json()["type"] == "auth/unauthorized"
