"""The mastery lock over the real database, wired into the learning gate."""

from app.modules.lms.application.engagement.service import EngagementService
from app.modules.lms.application.engagement.views import EngagementSettingsView
from app.modules.lms.domain.engagement.errors import SectionLockedError
from app.modules.lms.infrastructure.orm.course_version import CourseVersion
from app.modules.lms.wiring_engagement import build_engagement
from app.modules.lms.wiring_learning import LearningServices, build_learning
from app.shared.actor import Actor
from app.shared.wiring import ModuleDeps
from tests.lms.learning.builders import SeededCourse, add_staff
from tests.lms.learning.fakes.identity import FakeIdentityDirectory
from tests.lms.learning.fakes.preview_revisions import FakePreviewRevisions
from tests.lms.learning.scenarios import RIGHT, WRONG, quiz_course, take

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def engagement(deps: ModuleDeps, identity: FakeIdentityDirectory) -> EngagementService:
    """The engagement service as wired in production."""
    return build_engagement(deps, identity=identity)


@pytest.fixture
def locked_learning(
    deps: ModuleDeps,
    identity: FakeIdentityDirectory,
    previews: FakePreviewRevisions,
    engagement: EngagementService,
) -> LearningServices:
    """The learning use cases with the engagement step lock, as in production."""
    return build_learning(
        deps,
        identity=identity,
        preview_revisions=previews,
        step_lock=engagement.require_unlocked,
    )


async def _two_sections(
    maker: async_sessionmaker[AsyncSession], course: SeededCourse
) -> None:
    """Split the published outline: section 1 holds the quiz, section 2 the text."""
    quiz, text = course.step("quiz"), course.step("text")

    def entry(step_id: object, revision_id: object, title: str) -> dict[str, str]:
        return {
            "step_id": str(step_id),
            "revision_id": str(revision_id),
            "title": title,
        }

    outline = {
        "sections": [
            {
                "id": "sec-1",
                "title": "One",
                "steps": [entry(quiz.step_id, quiz.revision_id, "Quiz")],
            },
            {
                "id": "sec-2",
                "title": "Two",
                "steps": [entry(text.step_id, text.revision_id, "Reading")],
            },
        ]
    }
    async with maker() as session:
        await session.execute(
            update(CourseVersion)
            .where(CourseVersion.id == course.version_id)
            .values(outline=outline)
        )
        await session.commit()


async def test_lock_blocks_a_learner_below_the_threshold_until_mastered(
    maker: async_sessionmaker[AsyncSession],
    locked_learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
    teacher: Actor,
) -> None:
    """Section 2 stays closed while section 1 is under the threshold."""
    course, quiz = await quiz_course(
        maker, locked_learning, student, with_text_step=True
    )
    await _two_sections(maker, course)
    await add_staff(maker, course, teacher.user_id, permissions=["review", "edit"])
    await engagement.set_settings(
        teacher, course.id, EngagementSettingsView(unlock_threshold_pct=80)
    )
    text = course.step("text").step_id
    view = locked_learning.get_step_view

    await view.execute(student, course.id, quiz.step_id)
    with pytest.raises(SectionLockedError):
        await view.execute(student, course.id, text)
    await take(locked_learning, student, quiz, WRONG)
    with pytest.raises(SectionLockedError):
        await view.execute(student, course.id, text)

    await take(locked_learning, student, quiz, RIGHT)
    assert (await view.execute(student, course.id, text)).step_id == text


async def test_lock_never_blocks_staff(
    maker: async_sessionmaker[AsyncSession],
    locked_learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
    teacher: Actor,
) -> None:
    """Course staff open a locked section without any progress."""
    course, _ = await quiz_course(maker, locked_learning, student, with_text_step=True)
    await _two_sections(maker, course)
    await add_staff(maker, course, teacher.user_id, permissions=["review", "edit"])
    await engagement.set_settings(
        teacher, course.id, EngagementSettingsView(unlock_threshold_pct=100)
    )
    text = course.step("text").step_id

    await engagement.require_unlocked(teacher, course.id, text)
    view = await locked_learning.get_step_view.execute(teacher, course.id, text)
    assert view.step_id == text
    with pytest.raises(SectionLockedError):
        await engagement.require_unlocked(student, course.id, text)


async def test_lock_is_a_no_op_without_a_threshold(
    maker: async_sessionmaker[AsyncSession],
    locked_learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
) -> None:
    """With no threshold set every section is open to the learner."""
    course, _ = await quiz_course(maker, locked_learning, student, with_text_step=True)
    await _two_sections(maker, course)
    text = course.step("text").step_id

    await engagement.require_unlocked(student, course.id, text)
    view = await locked_learning.get_step_view.execute(student, course.id, text)
    assert view.step_id == text
