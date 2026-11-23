"""The flashcard grade route over HTTP and the real database."""

from types import SimpleNamespace

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.lms_engagement import ROUTERS
from app.modules.lms.domain.engagement.xp import card_xp
from app.modules.lms.infrastructure.orm.engagement import XpEvent
from app.modules.lms.wiring_engagement import build_engagement
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from app.shared.wiring import ModuleDeps
from tests.conftest import HttpClientFactory
from tests.lms.learning.builders import cards, content, seed_course
from tests.lms.learning.fakes.identity import FakeIdentityDirectory

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def engagement_client(
    http_client: HttpClientFactory,
    deps: ModuleDeps,
    identity: FakeIdentityDirectory,
    caller: dict[str, Actor],
) -> AsyncClient:
    """The engagement routes over the test transaction."""
    client: AsyncClient = await http_client(
        ROUTERS,
        {get_actor: lambda: caller["actor"]},
        lms=SimpleNamespace(engagement=build_engagement(deps, identity=identity)),
    )
    return client


async def test_grade_reschedules_the_card_and_awards_xp(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    engagement_client: AsyncClient,
    caller: dict[str, Actor],
    student: Actor,
    other_student: Actor,
) -> None:
    """An enrolled learner rates a card; bad ids, ratings and outsiders fail."""
    course = await seed_course(maker, steps=[("deck", content("Deck", cards()))])
    await learning.enroll_in_course.execute(student, course.id)
    step_id = course.step("deck").step_id
    url = f"/v1/lms/engagement/review/c:{step_id}:c1/grade"
    caller["actor"] = student

    response = await engagement_client.post(url, json={"rating": 3})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["xp"] == card_xp(3) > 0
    assert body["next_due"]
    async with maker() as session:
        events = (
            await session.scalars(
                select(XpEvent).where(XpEvent.user_id == student.user_id)
            )
        ).all()
    assert [(e.source, e.xp, e.course_id) for e in events] == [
        ("review", card_xp(3), course.id)
    ]

    assert (await engagement_client.post(url, json={"rating": 5})).status_code == 422
    missing = f"/v1/lms/engagement/review/c:{step_id}:nope/grade"
    assert (
        await engagement_client.post(missing, json={"rating": 3})
    ).status_code == 404
    garbled = "/v1/lms/engagement/review/x:1/grade"
    assert (
        await engagement_client.post(garbled, json={"rating": 3})
    ).status_code == 404
    caller["actor"] = other_student
    outsider = await engagement_client.post(url, json={"rating": 3})
    assert outsider.status_code == 404
