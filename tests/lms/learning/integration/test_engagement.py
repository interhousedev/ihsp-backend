"""Engagement over the real database: XP sync, review, quests and nudges."""

from datetime import timedelta

from app.modules.lms.application.engagement.service import EngagementService
from app.modules.lms.application.engagement.views import EngagementQuestInput
from app.modules.lms.domain.engagement.errors import QuestNotFoundError
from app.modules.lms.wiring_engagement import build_engagement
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from app.shared.clock import to_local
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.lms.learning.builders import add_staff
from tests.lms.learning.fakes.identity import FakeIdentityDirectory
from tests.lms.learning.scenarios import RIGHT, WRONG, quiz_course, take

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def engagement(deps: ModuleDeps, identity: FakeIdentityDirectory) -> EngagementService:
    """The engagement service as wired in production."""
    return build_engagement(deps, identity=identity)


async def test_summary_and_xp_sync_are_idempotent(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
) -> None:
    """Reading twice never awards the same attempt twice."""
    _, step = await quiz_course(maker, learning, student)
    await take(learning, student, step, RIGHT)

    first = await engagement.summary(student)
    second = await engagement.summary(student)
    history = await engagement.xp_history(student, 50)

    assert first.xp_total > 0
    assert second.xp_total == first.xp_total
    assert sum(i.xp for i in history.items) == first.xp_total
    assert first.streak.today_done


async def test_review_answer_reschedules_and_awards_xp(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
    clock: FixedClock,
) -> None:
    """Missed questions enter the queue; a right answer moves them out of it."""
    _, step = await quiz_course(maker, learning, student)
    await take(learning, student, step, WRONG)
    clock.advance(minutes=1)

    queue = await engagement.review_queue(student)
    questions = [i for i in queue.items if i.kind == "question"]
    assert len(questions) == 3
    item = next(i for i in questions if i.question and i.question["id"] == "q2")
    result = await engagement.answer(student, item.item_id, RIGHT["q2"])

    assert result.correct and result.xp > 0
    assert result.next_due > clock.now()
    left = await engagement.review_queue(student)
    assert item.item_id not in {i.item_id for i in left.items}


async def test_quests_crud_progress_and_nudge_candidates(
    maker: async_sessionmaker[AsyncSession],
    learning: LearningServices,
    engagement: EngagementService,
    student: Actor,
    teacher: Actor,
    clock: FixedClock,
) -> None:
    """Staff manage quests; learners see progress; the cron reads three nudges."""
    course, step = await quiz_course(maker, learning, student)
    await add_staff(maker, course, teacher.user_id, permissions=["review", "edit"])
    today = to_local(clock.now()).date()
    body = EngagementQuestInput(
        title="Five steps",
        goal_kind="steps",
        target=5,
        class_target=1,
        starts_on=today,
        ends_on=today + timedelta(days=1),
    )
    quest = await engagement.save_quest(teacher, course.id, body)
    renamed = await engagement.save_quest(
        teacher, course.id, body.model_copy(update={"title": "Go"}), quest.id
    )
    assert renamed.title == "Go"
    assert [q.id for q in (await engagement.course_quests(teacher, course.id)).items]
    await take(learning, student, step, WRONG)

    mine = (await engagement.my_quests(student)).items
    assert [q.title for q in mine] == ["Go"]
    assert mine[0].my_progress < mine[0].target

    clock.advance(days=1)
    nudges = await engagement.list_nudge_candidates(today + timedelta(days=1))
    types = {n.type for n in nudges if n.user_id == student.user_id}
    assert types == {"lms_review_due", "lms_streak_at_risk", "lms_deadline_soon"}

    await engagement.delete_quest(teacher, course.id, quest.id)
    with pytest.raises(QuestNotFoundError):
        await engagement.delete_quest(teacher, course.id, quest.id)
