"""The learner's own record: courses, mastery and submitted attempts (MCP).

Anti-cheating (D2): scores are always shown; per-question correctness only for
submitted, non-preview attempts; prompts, explanations and correct answers only
when the step's ``show_answers`` policy already shows them to the student on the
web. Open exam sittings live in step state, not in attempts, and never appear.
"""

import base64
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.lms.application.engagement.service import course_mastery
from app.modules.lms.application.learning.attempt_presenter import (
    number,
    review_allowed,
)
from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.progress_service import (
    current_progress_pct,
)
from app.modules.lms.application.learning.revision_loading import (
    find_test_block,
    load_revision,
)
from app.modules.lms.domain.access_rules import AccessState
from app.modules.lms.domain.learning.entities import Attempt, LiveVersion
from app.modules.lms.domain.learning.errors import (
    AttemptNotFoundError,
    CourseNotFoundError,
)
from app.modules.lms.domain.learning.grading import build_review, grade_attempt
from app.modules.lms.domain.learning.variant import points_of
from app.modules.lms.ports.learning.engagement import EngagementUnitOfWork
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError

from pydantic import BaseModel

MAX_PAGE = 50


class LearnerCourseView(BaseModel):
    """One enrolled course in the learner's record."""

    course_id: UUID
    title: str
    progress_pct: int
    badges_earned: int
    last_activity_at: datetime | None


class LearnerStepPointsView(BaseModel):
    """Test points of one step for the learner."""

    step_id: UUID
    title: str
    max_points: float
    best_points: float | None
    completed: bool


class LearnerSectionView(BaseModel):
    """Mastery of one section."""

    section_id: str
    title: str
    mastery_pct: int | None
    unlocked: bool
    steps: list[LearnerStepPointsView]


class LearnerCourseProgressView(BaseModel):
    """The learner's mastery map of one course."""

    course_id: UUID
    title: str
    progress_pct: int
    unlock_threshold_pct: int | None
    sections: list[LearnerSectionView]


class MyAttemptItemView(BaseModel):
    """A submitted attempt in the learner's list."""

    attempt_id: UUID
    step_id: UUID
    step_title: str
    section_title: str
    block_id: str
    attempt_no: int
    score: float
    max_score: float
    passed: bool
    submitted_at: datetime


class MyAttemptPageView(BaseModel):
    """One page of submitted attempts, newest first."""

    attempts: list[MyAttemptItemView]
    next_cursor: str | None


class MyAttemptTypeView(BaseModel):
    """Totals of one question type in an attempt."""

    type: str
    questions: int
    correct: int
    points: float
    max_points: float


class MyAttemptQuestionView(BaseModel):
    """One question of an attempt; the text fields only under the answers policy."""

    question_id: str
    type: str
    points: float
    max_points: float
    correct: bool
    prompt: str | None = None
    explanation: str | None = None
    correct_answer: dict[str, Any] | None = None


class MyAttemptView(BaseModel):
    """A submitted attempt of the learner with its per-type summary."""

    attempt_id: UUID
    course_id: UUID
    step_id: UUID
    block_id: str
    attempt_no: int
    score: float
    max_score: float
    passed: bool
    submitted_at: datetime
    review_shown: bool
    by_type: list[MyAttemptTypeView]
    questions: list[MyAttemptQuestionView]


def encode_cursor(submitted_at: datetime, attempt_id: UUID) -> str:
    """Return the opaque cursor after an attempt."""
    raw = f"{submitted_at.isoformat()}|{attempt_id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Return the key of a cursor; a malformed cursor is a validation error."""
    try:
        at, _, ident = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return datetime.fromisoformat(at), UUID(ident)
    except ValueError:  # binascii.Error and UnicodeDecodeError are ValueErrors
        raise ValidationFailedError(params={"cursor": cursor}) from None


class LearningRecordQueries:
    """Read-only views of the caller's own learning; nothing about anyone else."""

    def __init__(
        self, uow_factory: Callable[[], EngagementUnitOfWork], gate: AudienceGate
    ) -> None:
        """Store collaborators."""
        self.uow_factory = uow_factory
        self.gate = gate

    async def courses(self, actor: Actor) -> list[LearnerCourseView]:
        """Return the visible enrolled courses with progress, badges and activity."""
        async with self.uow_factory() as uow:
            enrollments = await uow.enrollments.list_for_user(actor.user_id)
            courses = {
                c.id: c
                for c in await uow.courses.get_many([e.course_id for e in enrollments])
            }
            versions = await uow.versions.get_many(
                [c.live_version_id for c in courses.values() if c.live_version_id]
            )
            access = await self.gate.courses(uow, actor, list(courses))
            last = await uow.attempts.last_submitted_by_course(
                actor.user_id, list(courses)
            )
            badges: dict[UUID, int] = {}
            for award in await uow.badges.awards_of(actor.user_id):
                if award.course_id is not None:
                    badges[award.course_id] = badges.get(award.course_id, 0) + 1
            out: list[LearnerCourseView] = []
            for enrollment in enrollments:
                course = courses.get(enrollment.course_id)
                if course is None or course.live_version_id is None:
                    continue
                version = versions.get(course.live_version_id)
                if version is None or access[course.id].state is AccessState.HIDDEN:
                    continue
                out.append(
                    LearnerCourseView(
                        course_id=course.id,
                        title=course.title,
                        progress_pct=await current_progress_pct(
                            uow, self.gate, enrollment, version
                        ),
                        badges_earned=badges.get(course.id, 0),
                        last_activity_at=last.get(course.id),
                    )
                )
        return sorted(out, key=lambda c: c.title.casefold())

    async def course_progress(
        self, actor: Actor, course_id: UUID
    ) -> LearnerCourseProgressView:
        """Return the mastery map of an enrolled course (as the engagement page)."""
        async with self.uow_factory() as uow:
            version, title, progress = await self._enrolled(uow, actor, course_id)
            threshold = await uow.engagement.unlock_threshold(course_id)
            sections = await course_mastery(
                uow, actor.user_id, version.manifest, threshold
            )
        return LearnerCourseProgressView(
            course_id=course_id,
            title=title,
            progress_pct=progress,
            unlock_threshold_pct=threshold,
            sections=[
                LearnerSectionView(
                    section_id=s.section_id,
                    title=s.title,
                    mastery_pct=s.mastery_pct,
                    unlocked=s.unlocked,
                    steps=[
                        LearnerStepPointsView(
                            step_id=p.step_id,
                            title=p.title,
                            max_points=number(p.max_points),
                            best_points=(
                                None if p.best_points is None else number(p.best_points)
                            ),
                            completed=p.completed,
                        )
                        for p in s.steps
                    ],
                )
                for s in sections
            ],
        )

    async def my_attempts(
        self,
        actor: Actor,
        course_id: UUID,
        *,
        step_id: UUID | None = None,
        limit: int = MAX_PAGE,
        cursor: str | None = None,
    ) -> MyAttemptPageView:
        """Return the caller's submitted attempts in an enrolled course."""
        limit = max(1, min(limit, MAX_PAGE))
        before = decode_cursor(cursor) if cursor else None
        async with self.uow_factory() as uow:
            version, _, _ = await self._enrolled(uow, actor, course_id)
            rows = await uow.attempts.list_submitted_for_user(
                actor.user_id,
                course_id,
                step_id=step_id,
                limit=limit + 1,
                before=before,
            )
        titles = {
            step.step_id: (step.title, section.title)
            for section in version.manifest.sections
            for step in section.steps
        }
        page = rows[:limit]
        items = [_item(a, titles.get(a.step_id, ("", ""))) for a in page]
        last = page[-1] if len(rows) > limit else None
        return MyAttemptPageView(
            attempts=items,
            next_cursor=(
                encode_cursor(last.submitted_at, last.id)
                if last is not None and last.submitted_at is not None
                else None
            ),
        )

    async def my_attempt(self, actor: Actor, attempt_id: UUID) -> MyAttemptView:
        """Return one submitted attempt of the caller under the answers policy."""
        async with self.uow_factory() as uow:
            attempt = await uow.attempts.get(attempt_id)
            if (
                attempt is None
                or attempt.user_id != actor.user_id
                or attempt.is_preview
                or attempt.submitted_at is None
            ):
                raise AttemptNotFoundError(params={"attempt_id": str(attempt_id)})
            step = await uow.steps.get(attempt.step_id)
            if step is None:
                raise AttemptNotFoundError(params={"attempt_id": str(attempt_id)})
            revision = await load_revision(uow, attempt.revision_id)
            test = find_test_block(revision.content, attempt.block_id)
            show = await review_allowed(uow, attempt, test)
        grade = grade_attempt(test, attempt.variant, attempt.answers)
        by_id = {q.id: q for q in test.questions}
        review = {
            item["question_id"]: item
            for item in build_review(test, attempt.variant, grade.correct)
        }
        questions: list[MyAttemptQuestionView] = []
        types: dict[str, MyAttemptTypeView] = {}
        for qid in attempt.variant.question_ids:
            question = by_id.get(qid)
            if question is None:
                continue
            correct = grade.correct.get(qid, False)
            max_points = points_of(question)
            earned = max_points if correct else Decimal(0)
            questions.append(
                MyAttemptQuestionView(
                    question_id=qid,
                    type=question.type,
                    points=number(earned),
                    max_points=number(max_points),
                    correct=correct,
                    prompt=question.prompt if show else None,
                    explanation=question.explanation if show else None,
                    correct_answer=review[qid]["correct_answer"] if show else None,
                )
            )
            row = types.setdefault(
                question.type,
                MyAttemptTypeView(
                    type=question.type,
                    questions=0,
                    correct=0,
                    points=0.0,
                    max_points=0.0,
                ),
            )
            row.questions += 1
            row.correct += int(correct)
            row.points += number(earned)
            row.max_points += number(max_points)
        return MyAttemptView(
            attempt_id=attempt.id,
            course_id=step.course_id,
            step_id=attempt.step_id,
            block_id=attempt.block_id,
            attempt_no=attempt.attempt_no,
            score=number(attempt.effective_score),
            max_score=number(attempt.max_score),
            passed=bool(attempt.passed),
            submitted_at=attempt.submitted_at,
            review_shown=show,
            by_type=list(types.values()),
            questions=questions,
        )

    async def _enrolled(
        self, uow: EngagementUnitOfWork, actor: Actor, course_id: UUID
    ) -> tuple[LiveVersion, str, int]:
        """Return the live version, title and progress; not enrolled is not found."""
        course = await uow.courses.get(course_id)
        enrollment = await uow.enrollments.get(course_id, actor.user_id)
        if course is None or enrollment is None or course.live_version_id is None:
            raise CourseNotFoundError(params={"course_id": str(course_id)})
        access = await self.gate.courses(uow, actor, [course_id])
        version = await uow.versions.get(course.live_version_id)
        if version is None or access[course_id].state is AccessState.HIDDEN:
            raise CourseNotFoundError(params={"course_id": str(course_id)})
        progress = await current_progress_pct(uow, self.gate, enrollment, version)
        return version, course.title, progress


def _item(attempt: Attempt, titles: tuple[str, str]) -> MyAttemptItemView:
    assert attempt.submitted_at is not None
    return MyAttemptItemView(
        attempt_id=attempt.id,
        step_id=attempt.step_id,
        step_title=titles[0],
        section_title=titles[1],
        block_id=attempt.block_id,
        attempt_no=attempt.attempt_no,
        score=number(attempt.effective_score),
        max_score=number(attempt.max_score),
        passed=bool(attempt.passed),
        submitted_at=attempt.submitted_at,
    )
