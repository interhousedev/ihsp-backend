"""Course badges over HTTP and the real database: design, award, views, image."""

from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.lms_learning import ROUTERS
from app.modules.lms.application.badges import BadgeService
from app.modules.lms.infrastructure.learning.uow import SqlLearningUnitOfWork
from app.modules.lms.infrastructure.orm.badge import BadgeAward
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.wiring import ModuleDeps
from tests.conftest import HttpClientFactory
from tests.fakes.certificates.world import FakeFiles
from tests.lms.learning.builders import add_staff, content, seed_course, text_block

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
BADGE: dict[str, Any] = {
    "name": {"en": "First step", "ru": "Первый шаг", "uz": "Birinchi qadam"},
    "description": {"en": "Finish a step"},
    "design": {"icon": "star", "shape": "circle", "color": "#336699"},
    "rule": {"event": "step_completed", "condition": None},
}


@pytest.fixture
def files() -> FakeFiles:
    """In-memory file storage."""
    return FakeFiles()


@pytest.fixture
async def badge_client(
    http_client: HttpClientFactory,
    learning: LearningServices,
    deps: ModuleDeps,
    files: FakeFiles,
    clock: Clock,
    caller: dict[str, Actor],
) -> AsyncClient:
    """The learning routes with the badge service over the test transaction."""

    def uow() -> SqlLearningUnitOfWork:
        return SqlLearningUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    client: AsyncClient = await http_client(
        ROUTERS,
        {get_actor: lambda: caller["actor"]},
        lms=SimpleNamespace(
            learning=learning,
            badges=BadgeService(uow, files, clock),  # type: ignore[arg-type]
        ),
    )
    return client


async def test_badge_is_designed_awarded_once_seen_and_shared(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    badge_client: AsyncClient,
    caller: dict[str, Actor],
    teacher: Actor,
    student: Actor,
    other_student: Actor,
    files: FakeFiles,
) -> None:
    """Staff create a badge, progress awards it once, the learner sees it."""
    course = await seed_course(
        maker,
        steps=[
            ("s1", content("One", text_block())),
            ("s2", content("Two", text_block())),
        ],
    )
    await add_staff(maker, course, teacher.user_id, permissions=("review", "edit"))
    base = f"/v1/lms/courses/{course.id}/badges"

    caller["actor"] = student
    denied = await badge_client.post(base, json=BADGE)
    assert denied.status_code == 403

    caller["actor"] = teacher
    created = await badge_client.post(base, json=BADGE)
    assert created.status_code == 201, created.text
    badge = created.json()
    assert badge["awarded_count"] == 0
    assert badge["rule"] == BADGE["rule"]

    caller["actor"] = student
    await learning.enroll_in_course.execute(student, course.id)
    locked = (await badge_client.get("/v1/lms/badges/mine")).json()
    assert locked["earned"] == []
    assert [b["badge"]["id"] for b in locked["locked"]] == [badge["id"]]

    await learning.mark_step_viewed.execute(student, course.step("s1").step_id)
    await learning.mark_step_viewed.execute(student, course.step("s2").step_id)
    async with maker() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(BadgeAward)
            .where(BadgeAward.user_id == student.user_id)
        )
    assert count == 1

    mine = (await badge_client.get("/v1/lms/badges/mine")).json()
    assert [e["badge"]["id"] for e in mine["earned"]] == [badge["id"]]
    assert mine["locked"] == []
    award_id = mine["earned"][0]["award_id"]
    assert mine["unseen"] == [award_id]

    caller["actor"] = other_student
    foreign = await badge_client.post(f"/v1/lms/badges/awards/{award_id}/seen")
    assert foreign.status_code == 404
    outsider = await badge_client.get(f"/v1/lms/users/{student.user_id}/badges")
    assert outsider.status_code == 200
    assert outsider.json()["earned"] == []

    caller["actor"] = student
    seen = await badge_client.post(f"/v1/lms/badges/awards/{award_id}/seen")
    assert seen.status_code == 204
    assert (await badge_client.get("/v1/lms/badges/mine")).json()["unseen"] == []

    caller["actor"] = teacher
    shared = (await badge_client.get(f"/v1/lms/users/{student.user_id}/badges")).json()
    assert [e["award_id"] for e in shared["earned"]] == [award_id]
    listed = (await badge_client.get(base)).json()
    assert listed["items"][0]["awarded_count"] == 1

    uploaded = await badge_client.post(
        f"{base}/{badge['id']}/image",
        files={"file": ("badge.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    image_url = uploaded.json()["design"]["image_url"]
    (file_id,) = files.files
    assert image_url == f"/files/{file_id}"
    assert files.objects[file_id] == PNG

    kept = await badge_client.put(
        f"{base}/{badge['id']}",
        json={**BADGE, "design": {**BADGE["design"], "image_url": image_url}},
    )
    assert kept.json()["design"]["image_url"] == image_url
    removed = await badge_client.put(
        f"{base}/{badge['id']}",
        json={**BADGE, "design": {**BADGE["design"], "image_url": None}},
    )
    assert removed.status_code == 200
    assert removed.json()["design"]["image_url"] is None
