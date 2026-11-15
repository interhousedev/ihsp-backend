"""Guests read published courses; everything else stays closed (`/v1/lms/public`)."""

import sys
from types import SimpleNamespace
from uuid import UUID

from app.interfaces.http.v1.lms_public import ROUTERS
from app.modules.lms.infrastructure.orm.course import Course
from app.modules.lms.wiring_learning import LearningServices
from tests.conftest import HttpClientFactory
from tests.lms.learning.builders import (
    SeededCourse,
    content,
    quiz,
    seed_course,
    text_block,
)
from tests.lms.learning.helpers import FORBIDDEN_KEYS, keys_of
from tests.lms.learning.scenarios import QUESTIONS

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def guest(
    http_client: HttpClientFactory, learning: LearningServices
) -> AsyncClient:
    """A client with the real authentication and no token."""
    client: AsyncClient = await http_client(
        ROUTERS, None, lms=SimpleNamespace(learning=learning)
    )
    return client


async def seed(
    maker: async_sessionmaker[AsyncSession],
    *,
    state: str = "published",
    **options: object,
) -> SeededCourse:
    """A course with a text step and a quiz step, in the given publish state."""
    course = await seed_course(
        maker,
        steps=[
            ("text", content("Reading", text_block())),
            ("quiz", content("Quiz", quiz("quiz", QUESTIONS, max_attempts=2))),
        ],
        **options,  # type: ignore[arg-type]
    )
    async with maker() as session:
        await session.execute(
            update(Course).where(Course.id == course.id).values(publish_state=state)
        )
        await session.commit()
    return course


async def test_a_guest_reads_a_published_course_and_its_lessons(
    guest: AsyncClient, maker: async_sessionmaker[AsyncSession]
) -> None:
    """The catalogue, landing, page and a lesson answer without a token."""
    course = await seed(maker)
    text_id = course.steps["text"].step_id
    quiz_id = course.steps["quiz"].step_id

    catalog = await guest.get("/v1/lms/public/courses")
    landing = await guest.get("/v1/lms/public/courses/algebra/landing")
    page = await guest.get("/v1/lms/public/courses/algebra")
    lesson = await guest.get(f"/v1/lms/public/courses/{course.id}/steps/{text_id}")
    test = await guest.get(f"/v1/lms/public/courses/{course.id}/steps/{quiz_id}")

    assert [c["slug"] for c in catalog.json()] == ["algebra"]
    assert (
        landing.status_code == 200 and landing.json()["enrolment"]["enrolled"] is False
    )
    body = page.json()
    assert body["enrolled"] is False and body["can_edit"] is False
    assert body["progress_pct"] is None and body["steps_completed"] is None
    assert [s["completed"] for sec in body["outline"] for s in sec["steps"]] == [
        None,
        None,
    ]
    assert lesson.status_code == 200
    assert lesson.json()["blocks"][0]["markdown"] == "Read this."
    assert test.status_code == 200
    quiz_block = test.json()["blocks"][0]
    assert quiz_block["best"] is None and quiz_block["open_attempt_id"] is None
    assert not (keys_of(test.json()) & FORBIDDEN_KEYS)


@pytest.mark.parametrize(
    "options",
    [
        {"state": "draft"},
        {"state": "archived", "status": "archived"},
        {"visibility": "invite", "invite_code": "secret"},
        {"publish": False, "state": "draft"},
    ],
)
async def test_unpublished_and_closed_courses_are_not_public(
    guest: AsyncClient,
    maker: async_sessionmaker[AsyncSession],
    options: dict[str, object],
) -> None:
    """Drafts, unpublished, archived and invite-only courses look missing."""
    course = await seed(maker, **options)  # type: ignore[arg-type]
    step_id = course.steps["text"].step_id if course.steps else UUID(int=1)

    catalog = await guest.get("/v1/lms/public/courses")
    page = await guest.get("/v1/lms/public/courses/algebra")
    landing = await guest.get("/v1/lms/public/courses/algebra/landing")
    lesson = await guest.get(f"/v1/lms/public/courses/{course.id}/steps/{step_id}")

    assert catalog.json() == []
    assert page.status_code == landing.status_code == lesson.status_code == 404


async def test_a_step_of_another_course_is_not_served(
    guest: AsyncClient, maker: async_sessionmaker[AsyncSession]
) -> None:
    """The course id in the path must own the step."""
    course = await seed(maker)
    other = await seed(maker, slug="geometry")
    step_id = course.steps["text"].step_id

    response = await guest.get(f"/v1/lms/public/courses/{other.id}/steps/{step_id}")

    assert response.status_code == 404


async def test_personal_endpoints_still_need_sign_in(
    anonymous_client: AsyncClient, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Enrolment, progress, the learner page and the signed-in catalogue say 401."""
    course = await seed(maker)
    step_id = course.steps["text"].step_id

    paths = [
        ("get", "/v1/lms/courses"),
        ("get", "/v1/lms/courses/algebra"),
        ("get", "/v1/lms/my-courses"),
        ("get", f"/v1/lms/courses/{course.id}/steps/{step_id}"),
        ("post", f"/v1/lms/courses/{course.id}/enroll"),
        ("post", f"/v1/lms/steps/{step_id}/viewed"),
    ]
    for method, path in paths:
        response = await getattr(anonymous_client, method)(path)
        assert response.status_code == 401, path


async def test_a_guest_page_can_be_asked_by_course_id(
    guest: AsyncClient, maker: async_sessionmaker[AsyncSession]
) -> None:
    """The player's address has only the id, so the page answers to it as well."""
    course = await seed(maker)
    draft = await seed(maker, state="draft", slug="hidden")

    page = await guest.get(f"/v1/lms/public/courses/{course.id}")
    hidden = await guest.get(f"/v1/lms/public/courses/{draft.id}")

    assert page.status_code == 200 and page.json()["slug"] == "algebra"
    assert hidden.status_code == 404


async def test_guest_routes_are_rate_limited(
    guest: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Over the per-address limit the guest routes answer 429."""
    module = sys.modules["app.interfaces.http.v1.lms_public.router"]
    monkeypatch.setattr(module, "GUEST_LIMIT", 2)

    codes = [(await guest.get("/v1/lms/public/courses")).status_code for _ in range(3)]

    assert codes == [200, 200, 429]
