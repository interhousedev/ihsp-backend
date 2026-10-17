"""H5P and interactive video blocks of a live step: launch, results, answers."""

from typing import Any
from uuid import uuid4

from app.modules.lms.application.h5p_links import H5PLinks
from app.modules.lms.application.learning.views import LearningH5PBlockView
from app.modules.lms.domain.h5p_token import package_prefix
from app.modules.lms.domain.learning.block_results import XAPI_COMPLETED
from app.modules.lms.domain.learning.errors import (
    H5PNotFoundError,
    InteractionNotFoundError,
    NotEnrolledError,
)
from app.modules.lms.domain.step_content import H5PBlock, InteractiveVideoBlock
from app.modules.lms.infrastructure.h5p_memory_store import MemoryH5PStore
from app.modules.lms.wiring_learning import LearningServices, build_learning
from app.shared.actor import Actor
from app.shared.wiring import ModuleDeps
from tests.lms.learning.builders import content, seed_course
from tests.lms.learning.fakes.identity import FakeIdentityDirectory
from tests.lms.learning.fakes.preview_revisions import FakePreviewRevisions

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PACKAGE = uuid4()


@pytest.fixture
def store() -> MemoryH5PStore:
    return MemoryH5PStore()


@pytest.fixture
def services(
    deps: ModuleDeps,
    identity: FakeIdentityDirectory,
    previews: FakePreviewRevisions,
    store: MemoryH5PStore,
) -> LearningServices:
    links = H5PLinks(b"test-key", deps.clock, store)
    return build_learning(
        deps, identity=identity, preview_revisions=previews, h5p_links=links
    )


def _video() -> Any:  # noqa: ANN401
    return InteractiveVideoBlock.model_validate(
        {
            "id": "iv",
            "url": "https://youtu.be/abc",
            "interactions": [
                {
                    "id": "q1",
                    "at_sec": 10,
                    "text": "Which?",
                    "options": [
                        {"id": "a", "text": "A", "correct": True},
                        {"id": "b", "text": "B"},
                    ],
                }
            ],
        }
    )


async def _course(maker: async_sessionmaker[AsyncSession]) -> Any:  # noqa: ANN401
    h5p: Any = H5PBlock(id="h", package_id=str(PACKAGE), passing_score_pct=50)
    return await seed_course(maker, steps=[("s", content("Lesson", h5p, _video()))])


async def test_h5p_launch_result_and_step_view(
    maker: async_sessionmaker[AsyncSession],
    services: LearningServices,
    student: Actor,
    store: MemoryH5PStore,
) -> None:
    course = await _course(maker)
    step_id = course.step("s").step_id
    await services.enroll_in_course.execute(student, course.id)
    await store.put(package_prefix(course.id, PACKAGE) + "h5p.json", b"{}", "x")

    launch = await services.get_h5p_launch.execute(student, course.id, step_id, "h")
    token = launch.base_url.removeprefix("/v1/lms/h5p/").strip("/")
    assert (await services.h5p_links.read(token, "h5p.json")).data == b"{}"

    statement = {
        "verb": {"id": XAPI_COMPLETED},
        "result": {"score": {"raw": 3, "max": 4}, "completion": True},
    }
    result = await services.record_h5p_result.execute(student, step_id, "h", statement)
    assert (result.score, result.max_score, result.completed) == (3, 4, True)

    view = await services.get_step_view.execute(student, course.id, step_id)
    h5p = next(b for b in view.blocks if b.id == "h")
    assert isinstance(h5p, LearningH5PBlockView)
    assert h5p.passed and h5p.result is not None and h5p.result.score == 3


async def test_interactive_video_answers_are_graded_and_shown(
    maker: async_sessionmaker[AsyncSession],
    services: LearningServices,
    student: Actor,
) -> None:
    course = await _course(maker)
    step_id = course.step("s").step_id
    await services.enroll_in_course.execute(student, course.id)

    graded = await services.answer_interaction.execute(
        student, step_id, "iv", "q1", ["a"]
    )
    assert graded.answer.correct and graded.correct_option_ids == ["a"]
    assert graded.result.completed and graded.result.score == 1
    with pytest.raises(InteractionNotFoundError):
        await services.answer_interaction.execute(student, step_id, "iv", "zz", [])

    view = await services.get_step_view.execute(student, course.id, step_id)
    video = next(b for b in view.blocks if b.id == "iv")
    dumped = video.model_dump()
    assert video.passed and dumped["answers"]["q1"]["correct"] is True
    assert "correct" not in dumped["interactions"][0]["options"][0]


async def test_strangers_and_unknown_blocks_get_nothing(
    maker: async_sessionmaker[AsyncSession],
    services: LearningServices,
    student: Actor,
) -> None:
    course = await _course(maker)
    step_id = course.step("s").step_id
    with pytest.raises(NotEnrolledError):
        await services.get_h5p_launch.execute(student, course.id, step_id, "h")
    await services.enroll_in_course.execute(student, course.id)
    with pytest.raises(H5PNotFoundError):
        await services.get_h5p_launch.execute(student, course.id, step_id, "iv")
