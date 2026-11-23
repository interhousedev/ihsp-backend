"""Routes of the engagement features: XP, streak, daily review, mastery, quests."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.schemas import LearningAnswerBody
from app.modules.lms.application.engagement.views import (
    EngagementAnswerResultView,
    EngagementGradeResultView,
    EngagementMasteryView,
    EngagementQuestInput,
    EngagementQuestListView,
    EngagementQuestView,
    EngagementReviewQueueView,
    EngagementSettingsView,
    EngagementSummaryView,
    EngagementXpListView,
)
from app.shared.actor import Actor

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

ActorDep = Annotated[Actor, Depends(get_actor)]
ContainerDep = Annotated[Container, Depends(get_container)]

router = APIRouter(prefix="/v1/lms", tags=["lms"])


class ReviewAnswerBody(BaseModel):
    """An answer to a review question (same shape as a test answer)."""

    answer: LearningAnswerBody


class ReviewGradeBody(BaseModel):
    """A flashcard rating: 1 again, 2 hard, 3 good, 4 easy."""

    rating: int = Field(ge=1, le=4)


@router.get("/engagement/summary", operation_id="lms_engagement_summary")
async def engagement_summary(
    actor: ActorDep, container: ContainerDep
) -> EngagementSummaryView:
    """Return XP, level, the school-week streak, due reviews and the weekly goal."""
    return await container.lms.engagement.summary(actor)


@router.get("/engagement/xp", operation_id="lms_engagement_xp")
async def engagement_xp(
    actor: ActorDep,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> EngagementXpListView:
    """Return the newest XP awards."""
    return await container.lms.engagement.xp_history(actor, limit)


@router.get("/engagement/review", operation_id="lms_engagement_review")
async def engagement_review(
    actor: ActorDep, container: ContainerDep
) -> EngagementReviewQueueView:
    """Return today's due questions and flashcards (at most 20 answers a day)."""
    return await container.lms.engagement.review_queue(actor)


@router.post(
    "/engagement/review/{item_id}/answer",
    operation_id="lms_engagement_review_answer",
)
async def engagement_review_answer(
    item_id: str, body: ReviewAnswerBody, actor: ActorDep, container: ContainerDep
) -> EngagementAnswerResultView:
    """Check a review answer, reschedule the question and award XP."""
    return await container.lms.engagement.answer(
        actor, item_id, body.answer.model_dump(exclude_none=True)
    )


@router.post(
    "/engagement/review/{item_id}/grade",
    operation_id="lms_engagement_review_grade",
)
async def engagement_review_grade(
    item_id: str, body: ReviewGradeBody, actor: ActorDep, container: ContainerDep
) -> EngagementGradeResultView:
    """Rate a due flashcard and award XP."""
    return await container.lms.engagement.grade_card(actor, item_id, body.rating)


@router.get(
    "/engagement/courses/{course_id}/mastery",
    operation_id="lms_engagement_mastery",
)
async def engagement_mastery(
    course_id: UUID, actor: ActorDep, container: ContainerDep
) -> EngagementMasteryView:
    """Return the learner's mastery map of a course."""
    return await container.lms.engagement.mastery(actor, course_id)


@router.get("/engagement/quests", operation_id="lms_engagement_quests")
async def engagement_quests(
    actor: ActorDep, container: ContainerDep
) -> EngagementQuestListView:
    """Return the running class quests of the learner's courses."""
    return await container.lms.engagement.my_quests(actor)


# - - - staff - - -


@router.get(
    "/courses/{course_id}/engagement-settings",
    operation_id="lms_engagement_get_settings",
)
async def engagement_get_settings(
    course_id: UUID, actor: ActorDep, container: ContainerDep
) -> EngagementSettingsView:
    """Return the mastery unlock threshold (course staff with `review`)."""
    return await container.lms.engagement.get_settings(actor, course_id)


@router.put(
    "/courses/{course_id}/engagement-settings",
    operation_id="lms_engagement_set_settings",
)
async def engagement_set_settings(
    course_id: UUID,
    body: EngagementSettingsView,
    actor: ActorDep,
    container: ContainerDep,
) -> EngagementSettingsView:
    """Set the mastery unlock threshold; null turns the lock off (`edit`)."""
    return await container.lms.engagement.set_settings(actor, course_id, body)


@router.get(
    "/courses/{course_id}/quests", operation_id="lms_engagement_list_course_quests"
)
async def engagement_list_course_quests(
    course_id: UUID, actor: ActorDep, container: ContainerDep
) -> EngagementQuestListView:
    """Return every quest of a course (course staff with `review`)."""
    return await container.lms.engagement.course_quests(actor, course_id)


@router.post(
    "/courses/{course_id}/quests",
    operation_id="lms_engagement_create_quest",
    status_code=201,
)
async def engagement_create_quest(
    course_id: UUID,
    body: EngagementQuestInput,
    actor: ActorDep,
    container: ContainerDep,
) -> EngagementQuestView:
    """Create a class quest of at most 31 days (course staff with `edit`)."""
    return await container.lms.engagement.save_quest(actor, course_id, body)


@router.patch(
    "/courses/{course_id}/quests/{quest_id}",
    operation_id="lms_engagement_update_quest",
)
async def engagement_update_quest(
    course_id: UUID,
    quest_id: UUID,
    body: EngagementQuestInput,
    actor: ActorDep,
    container: ContainerDep,
) -> EngagementQuestView:
    """Replace a class quest (course staff with `edit`)."""
    return await container.lms.engagement.save_quest(actor, course_id, body, quest_id)


@router.delete(
    "/courses/{course_id}/quests/{quest_id}",
    operation_id="lms_engagement_delete_quest",
    status_code=204,
)
async def engagement_delete_quest(
    course_id: UUID, quest_id: UUID, actor: ActorDep, container: ContainerDep
) -> Response:
    """Delete a class quest."""
    await container.lms.engagement.delete_quest(actor, course_id, quest_id)
    return Response(status_code=204)
