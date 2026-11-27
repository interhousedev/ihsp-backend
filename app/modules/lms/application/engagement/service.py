"""Engagement use cases: XP sync, summary, daily review, mastery, quests, nudges.

XP is synced lazily: every read scans the learner's new completions and
submitted attempts since a watermark and records awards idempotently, so the
attempt and step flows stay untouched. Missed single/multiple/text/number
questions enter the FSRS review queue at the same time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from app.modules.lms.application.engagement.views import (
    EngagementAnswerResultView,
    EngagementCardView,
    EngagementGradeResultView,
    EngagementMasterySectionView,
    EngagementMasteryStepView,
    EngagementMasteryView,
    EngagementQuestInput,
    EngagementQuestListView,
    EngagementQuestView,
    EngagementReviewItemView,
    EngagementReviewQueueView,
    EngagementSettingsView,
    EngagementStreakView,
    EngagementSummaryView,
    EngagementWeekDayView,
    EngagementXpItemView,
    EngagementXpListView,
)
from app.modules.lms.application.learning.audience import AudienceGate
from app.modules.lms.application.learning.step_context import (
    load_course,
    staff_access,
)
from app.modules.lms.domain.access_rules import AccessState
from app.modules.lms.domain.engagement import fsrs
from app.modules.lms.domain.engagement.errors import (
    QuestDatesInvalidError,
    QuestNotFoundError,
    ReviewItemNotFoundError,
    SectionLockedError,
)
from app.modules.lms.domain.engagement.mastery import (
    SectionMastery,
    StepPoints,
    best_by_step,
    mastery_map,
)
from app.modules.lms.domain.engagement.nudges import (
    DEADLINE_SOON,
    REVIEW_DUE,
    STREAK_AT_RISK,
    Nudge,
)
from app.modules.lms.domain.engagement.streak import HISTORY_DAYS, compute_streak
from app.modules.lms.domain.engagement.xp import (
    DAILY_REVIEW_LIMIT,
    DAILY_TEST_XP_LIMIT,
    STEP_COMPLETED_XP,
    best_gain_xp,
    capped,
    card_xp,
    level_of,
    question_xp,
)
from app.modules.lms.domain.learning.access import EDIT, REVIEW
from app.modules.lms.domain.learning.cards import state_from_json, state_to_json
from app.modules.lms.domain.learning.errors import (
    CardNotFoundError,
    NotEnrolledError,
)
from app.modules.lms.domain.learning.grading import (
    correct_answer_of,
    grade_attempt,
    is_correct,
    review_visible,
)
from app.modules.lms.domain.learning.live import LiveManifest, LiveStep
from app.modules.lms.domain.learning.points import block_max_points
from app.modules.lms.domain.learning.variant import Variant
from app.modules.lms.domain.step_content import (
    FlashcardsBlock,
    Question,
    StepContent,
    TestBlock,
)
from app.modules.lms.domain.student_render import render_questions
from app.modules.lms.ports.learning.engagement import (
    EngagementUnitOfWork,
    QuestRecord,
)
from app.shared import srs
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, to_local
from app.shared.ids import new_id

EngagementUowFactory = Callable[[], EngagementUnitOfWork]


class LevelHook(Protocol):
    """Told after a commit that a learner earned XP in some scopes."""

    async def after_xp(self, user_id: UUID, course_ids: set[UUID | None]) -> None:
        """Track level-ups of the learner (None is a platform-only award)."""
        ...


REVIEWABLE_TYPES = frozenset({"single", "multiple", "text", "number"})
SYNC_OVERLAP = timedelta(minutes=10)
RATINGS = {
    1: srs.Rating.AGAIN,
    2: srs.Rating.HARD,
    3: srs.Rating.MEDIUM,
    4: srs.Rating.EASY,
}
MAX_QUEST_DAYS = 31


def _tests(content: StepContent) -> list[TestBlock]:
    return [b for b in content.blocks if isinstance(b, TestBlock)]


def _test(content: StepContent, block_id: str) -> TestBlock | None:
    return next((b for b in _tests(content) if b.id == block_id), None)


def _question(test: TestBlock | None, qid: str) -> Question | None:
    return next((q for q in test.questions if q.id == qid), None) if test else None


def _option_order(question: Question) -> dict[str, list[str]]:
    return {question.id: [o.id for o in question.options or []]}


@dataclass(frozen=True, slots=True)
class _DueCard:
    course_id: UUID
    step_id: UUID
    card_id: str
    front: str
    back: str
    due_at: datetime


@dataclass(frozen=True, slots=True)
class _OpenStep:
    """A live step the learner may open right now."""

    course_id: UUID
    live: LiveStep


class EngagementService:
    """Every engagement use case; one source of XP and levels for all clients."""

    def __init__(
        self,
        uow_factory: EngagementUowFactory,
        clock: Clock,
        gate: AudienceGate,
        levels: LevelHook | None = None,
    ) -> None:
        """Store collaborators; `levels` announces level-ups after XP commits."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.gate = gate
        self.levels = levels

    def _after_xp(
        self, uow: EngagementUnitOfWork, user_id: UUID, courses: set[UUID | None]
    ) -> None:
        """Track level-ups once the transaction that recorded the XP commits."""
        if self.levels is None or not courses:
            return
        hook = self.levels

        async def run() -> None:
            await hook.after_xp(user_id, courses)

        uow.after_commit(run)

    # - - - access - - -

    async def _open_steps(
        self, uow: EngagementUnitOfWork, actor: Actor
    ) -> dict[UUID, _OpenStep]:
        """Return the live steps of enrolled courses the audience rules open.

        Review items and flashcards of other steps (unenrolled, unpublished,
        removed from the outline or closed to the learner) are hidden.
        """
        enrollments = await uow.enrollments.list_for_user(actor.user_id)
        courses = [
            c
            for c in await uow.courses.get_many([e.course_id for e in enrollments])
            if c.live_version_id is not None
        ]
        versions = await uow.versions.get_many(
            [c.live_version_id for c in courses if c.live_version_id]
        )
        access = await self.gate.courses(uow, actor, [c.id for c in courses])
        result: dict[UUID, _OpenStep] = {}
        for course in courses:
            version = versions.get(course.live_version_id)  # type: ignore[arg-type]
            if version is None:
                continue
            for live in version.manifest.steps():
                if access[course.id].step(live.step_id) is AccessState.OPEN:
                    result[live.step_id] = _OpenStep(course.id, live)
        return result

    async def _reveals(
        self, uow: EngagementUnitOfWork, user_id: UUID, step_id: UUID, test: TestBlock
    ) -> bool:
        """Return True when the test's `show_answers` lets the learner see answers."""
        config = test.config
        if config.show_answers in ("after_submit", "never"):
            return config.show_answers == "after_submit"
        passed = test.id in await uow.attempts.passed_block_ids(user_id, step_id)
        left = (
            None
            if config.max_attempts is None
            else config.max_attempts
            - await uow.attempts.count(user_id, step_id, test.id)
        )
        return review_visible(config.show_answers, passed=passed, attempts_left=left)

    # - - - sync - - -

    async def _sync(self, uow: EngagementUnitOfWork, user_id: UUID) -> None:
        """Record XP and queue missed questions for facts since the watermark.

        A test earns XP only when it beats the learner's best at its block, under
        a daily cap; missed questions are queued only where `show_answers`
        already lets the learner see the answers.
        """
        repo = uow.engagement
        now = self.clock.now()
        _, synced = await repo.profile(user_id)
        since = synced - SYNC_OVERLAP if synced else None
        completions = await repo.completions_since(user_id, since)
        attempts = await repo.attempts_since(user_id, since)
        courses = await repo.course_of_steps(
            list({s for s, _ in completions} | {a.step_id for a in attempts})
        )
        earned: set[UUID | None] = set()
        for step_id, at in completions:
            if await repo.add_xp(
                user_id,
                courses.get(step_id),
                "step",
                str(step_id),
                STEP_COMPLETED_XP,
                to_local(at).date(),
            ):
                earned.add(courses.get(step_id))
        revisions = await uow.revisions.get_many(
            list({a.revision_id for a in attempts})
        )
        for attempt in attempts:
            course_id = courses.get(attempt.step_id)
            day = to_local(attempt.submitted_at).date()
            earlier = await repo.scores_before(
                user_id, attempt.step_id, attempt.block_id, attempt.submitted_at
            )
            gain = capped(
                best_gain_xp(attempt.score, attempt.max_score, earlier),
                await repo.xp_on(user_id, day, "test"),
                DAILY_TEST_XP_LIMIT,
            )
            if gain > 0 and await repo.add_xp(
                user_id, course_id, "test", str(attempt.id), gain, day
            ):
                earned.add(course_id)
            await self._queue_misses(
                uow, user_id, attempt, course_id, revisions.get(attempt.revision_id)
            )
        await repo.mark_synced(user_id, now)
        self._after_xp(uow, user_id, earned)

    async def _queue_misses(
        self,
        uow: EngagementUnitOfWork,
        user_id: UUID,
        attempt: Any,
        course_id: UUID | None,
        revision: Any,
    ) -> None:
        """Queue the wrong answers of one attempt for review when answers show."""
        test = _test(revision.content, attempt.block_id) if revision else None
        if test is None or course_id is None:
            return
        if not await self._reveals(uow, user_id, attempt.step_id, test):
            return
        grade = grade_attempt(test, Variant.from_json(attempt.variant), attempt.answers)
        types = {q.id: q.type for q in test.questions}
        for qid, ok in grade.correct.items():
            if ok or types.get(qid) not in REVIEWABLE_TYPES:
                continue
            await uow.engagement.add_review_item(
                user_id=user_id,
                course_id=course_id,
                step_id=attempt.step_id,
                revision_id=attempt.revision_id,
                block_id=attempt.block_id,
                question_id=qid,
                state=fsrs.new_item(attempt.submitted_at),
            )

    # - - - summary - - -

    async def summary(self, actor: Actor) -> EngagementSummaryView:
        """Return XP, level, streak, due reviews and the weekly goal."""
        today = self._today()
        async with self.uow_factory() as uow:
            await self._sync(uow, actor.user_id)
            await uow.commit()
            goal, _ = await uow.engagement.profile(actor.user_id)
            total = await uow.engagement.xp_total(actor.user_id)
            days = await uow.engagement.active_days(
                actor.user_id, today - timedelta(days=HISTORY_DAYS)
            )
            open_steps = await self._open_steps(uow, actor)
            due = await uow.engagement.due_count(
                actor.user_id, self.clock.now(), list(open_steps)
            )
            due += len(await self._due_cards(uow, actor.user_id, open_steps))
        streak = compute_streak(days, today)
        level = level_of(total)
        return EngagementSummaryView(
            xp_total=total,
            level=level.level,
            xp_into_level=level.xp_into_level,
            xp_for_next=level.xp_for_next,
            streak=EngagementStreakView(
                current=streak.current,
                best=streak.best,
                freezes=streak.freezes,
                today_done=streak.today_done,
                week=[
                    EngagementWeekDayView(date=d.date, state=d.state)
                    for d in streak.week
                ],
            ),
            review_due=due,
            weekly_goal_days=goal,
        )

    async def xp_history(self, actor: Actor, limit: int) -> EngagementXpListView:
        """Return the newest XP awards."""
        async with self.uow_factory() as uow:
            await self._sync(uow, actor.user_id)
            await uow.commit()
            records = await uow.engagement.recent_xp(actor.user_id, limit)
        return EngagementXpListView(
            items=[
                EngagementXpItemView(source=r.source, ref=r.ref, xp=r.xp, at=r.at)
                for r in records
            ]
        )

    # - - - daily review - - -

    def _today(self) -> date:
        return to_local(self.clock.now()).date()

    async def _due_cards(
        self,
        uow: EngagementUnitOfWork,
        user_id: UUID,
        open_steps: dict[UUID, _OpenStep],
    ) -> list[_DueCard]:
        """Return studied flashcards of open steps whose shared-SRS state is due."""
        now = self.clock.now()
        stored = await uow.states.cards_by_step(user_id, list(open_steps))
        wanted = [o.live for o in open_steps.values() if stored.get(o.live.step_id)]
        revisions = await uow.revisions.get_many([s.revision_id for s in wanted])
        course_of = {s: o.course_id for s, o in open_steps.items()}
        due: list[_DueCard] = []
        for live in wanted:
            revision = revisions.get(live.revision_id)
            states = stored[live.step_id]
            cards = [
                card
                for block in (revision.content.blocks if revision else [])
                if isinstance(block, FlashcardsBlock)
                for card in block.cards
                if card.id in states
            ]
            for card in cards:
                state = state_from_json(states[card.id])
                if state.state is srs.CardState.NEW or state.due_at is None:
                    continue
                if state.due_at <= now:
                    due.append(
                        _DueCard(
                            course_of[live.step_id],
                            live.step_id,
                            card.id,
                            card.front,
                            card.back,
                            state.due_at,
                        )
                    )
        return sorted(due, key=lambda c: c.due_at)

    async def review_queue(self, actor: Actor) -> EngagementReviewQueueView:
        """Return today's due questions and flashcards, at most 20 answers a day."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            await self._sync(uow, actor.user_id)
            await uow.commit()
            left = DAILY_REVIEW_LIMIT - await uow.engagement.reviews_on(
                actor.user_id, self._today()
            )
            if left <= 0:
                return EngagementReviewQueueView(items=[])
            open_steps = await self._open_steps(uow, actor)
            items: list[EngagementReviewItemView] = []
            due = await uow.engagement.due_items(
                actor.user_id, now, left, list(open_steps)
            )
            revisions = await uow.revisions.get_many(list({i.revision_id for i in due}))
            for item in due:
                revision = revisions.get(item.revision_id)
                test = _test(revision.content, item.block_id) if revision else None
                question = _question(test, item.question_id)
                if question is None or test is None:
                    continue
                if not await self._reveals(uow, actor.user_id, item.step_id, test):
                    continue
                rendered = render_questions(
                    test, [question.id], _option_order(question)
                )[0]
                items.append(
                    EngagementReviewItemView(
                        item_id=f"q:{item.id}",
                        kind="question",
                        course_id=item.course_id,
                        step_id=item.step_id,
                        question=rendered,
                        card=None,
                    )
                )
            for card in (await self._due_cards(uow, actor.user_id, open_steps))[
                : max(left - len(items), 0)
            ]:
                items.append(
                    EngagementReviewItemView(
                        item_id=f"c:{card.step_id}:{card.card_id}",
                        kind="flashcard",
                        course_id=card.course_id,
                        step_id=card.step_id,
                        question=None,
                        card=EngagementCardView(front=card.front, back=card.back),
                    )
                )
        return EngagementReviewQueueView(items=items)

    async def _award_review(
        self,
        uow: EngagementUnitOfWork,
        user_id: UUID,
        course_id: UUID,
        ref: str,
        xp: int,
    ) -> int:
        """Record review XP unless the daily limit is reached; return the award."""
        today = self._today()
        if await uow.engagement.reviews_on(user_id, today) >= DAILY_REVIEW_LIMIT:
            return 0
        if await uow.engagement.add_xp(user_id, course_id, "review", ref, xp, today):
            self._after_xp(uow, user_id, {course_id})
        return xp

    async def answer(
        self, actor: Actor, item_id: str, answer: dict[str, Any]
    ) -> EngagementAnswerResultView:
        """Check a due review answer, reschedule it with FSRS and award XP.

        Only a due item of a step the learner may open right now is answerable;
        the correct answer and explanation follow the test's `show_answers`.
        """
        raw = item_id.removeprefix("q:")
        try:
            uid = UUID(raw)
        except ValueError:
            raise ReviewItemNotFoundError(params={"item_id": item_id}) from None
        now = self.clock.now()
        async with self.uow_factory() as uow:
            item = await uow.engagement.get_item(uid)
            if (
                item is None
                or item.user_id != actor.user_id
                or item.state.due_at > now
                or item.step_id not in await self._open_steps(uow, actor)
            ):
                raise ReviewItemNotFoundError(params={"item_id": item_id})
            revision = await uow.revisions.get(item.revision_id)
            test = _test(revision.content, item.block_id) if revision else None
            question = _question(test, item.question_id)
            if question is None or test is None:
                raise ReviewItemNotFoundError(params={"item_id": item_id})
            reveal = await self._reveals(uow, actor.user_id, item.step_id, test)
            correct = is_correct(question, answer)
            state = fsrs.review(item.state, fsrs.GOOD if correct else fsrs.AGAIN, now)
            await uow.engagement.save_item(item.id, state)
            xp = await self._award_review(
                uow,
                actor.user_id,
                item.course_id,
                f"q:{item.id}:{now.isoformat()}",
                question_xp(correct),
            )
            await uow.commit()
        variant = Variant(
            question_ids=(question.id,), option_order=_option_order(question)
        )
        return EngagementAnswerResultView(
            correct=correct,
            correct_answer=correct_answer_of(question, variant) if reveal else None,
            explanation=question.explanation if reveal else None,
            next_due=state.due_at,
            xp=xp,
        )

    async def grade_card(
        self, actor: Actor, item_id: str, rating: int
    ) -> EngagementGradeResultView:
        """Rate a course flashcard of an open step with the shared scheduler."""
        parts = item_id.split(":", 2)
        if len(parts) != 3 or parts[0] != "c":
            raise ReviewItemNotFoundError(params={"item_id": item_id})
        try:
            step_id = UUID(parts[1])
        except ValueError:
            raise ReviewItemNotFoundError(params={"item_id": item_id}) from None
        card_id = parts[2]
        now = self.clock.now()
        async with self.uow_factory() as uow:
            step = (await self._open_steps(uow, actor)).get(step_id)
            if step is None:
                raise ReviewItemNotFoundError(params={"item_id": item_id})
            revision = await uow.revisions.get(step.live.revision_id)
            known = revision is not None and any(
                card.id == card_id
                for block in revision.content.blocks
                if isinstance(block, FlashcardsBlock)
                for card in block.cards
            )
            if not known:
                raise CardNotFoundError(params={"card_id": card_id})
            state = await uow.states.get(actor.user_id, step_id)
            before = state_from_json((state.cards if state else {}).get(card_id))
            after = srs.review(before, RATINGS[rating], now)
            await uow.states.save_card(
                actor.user_id, step_id, card_id, state_to_json(after), now=now
            )
            xp = await self._award_review(
                uow,
                actor.user_id,
                step.course_id,
                f"c:{step_id}:{card_id}:{now.isoformat()}",
                card_xp(rating),
            )
            await uow.commit()
        return EngagementGradeResultView(next_due=after.due_at or now, xp=xp)

    # - - - mastery - - -

    async def _mastery(
        self,
        uow: EngagementUnitOfWork,
        user_id: UUID,
        manifest: LiveManifest,
        threshold: int | None,
    ) -> list[SectionMastery]:
        steps = manifest.steps()
        step_ids = [s.step_id for s in steps]
        revisions = await uow.revisions.get_many([s.revision_id for s in steps])
        best = await uow.attempts.best_scores(user_id, step_ids)
        completed = set(await uow.states.completed_step_ids(user_id, step_ids))
        sections = []
        for section in manifest.sections:
            points = []
            for live in section.steps:
                revision = revisions.get(live.revision_id)
                tests = _tests(revision.content) if revision else []
                points.append(
                    StepPoints(
                        step_id=live.step_id,
                        title=live.title,
                        max_points=sum(
                            (block_max_points(t) for t in tests), Decimal(0)
                        ),
                        best_points=best_by_step(
                            best, live.step_id, [t.id for t in tests]
                        ),
                        completed=live.step_id in completed,
                    )
                )
            sections.append((section.id, section.title, points))
        return mastery_map(sections, threshold)

    async def mastery(self, actor: Actor, course_id: UUID) -> EngagementMasteryView:
        """Return the learner's mastery map of a course they are enrolled in."""
        async with self.uow_factory() as uow:
            course = await load_course(uow, course_id)
            if await uow.enrollments.get(course_id, actor.user_id) is None:
                raise NotEnrolledError(params={"course_id": str(course_id)})
            threshold = await uow.engagement.unlock_threshold(course_id)
            version = (
                await uow.versions.get(course.live_version_id)
                if course.live_version_id
                else None
            )
            sections = (
                await self._mastery(uow, actor.user_id, version.manifest, threshold)
                if version
                else []
            )
        return EngagementMasteryView(
            unlock_threshold_pct=threshold,
            sections=[
                EngagementMasterySectionView(
                    section_id=s.section_id,
                    title=s.title,
                    mastery_pct=s.mastery_pct,
                    unlocked=s.unlocked,
                    steps=[
                        EngagementMasteryStepView(
                            step_id=p.step_id,
                            title=p.title,
                            best_pct=p.best_pct,
                            completed=p.completed,
                        )
                        for p in s.steps
                    ],
                )
                for s in sections
            ],
        )

    async def require_unlocked(
        self, actor: Actor | None, course_id: UUID, step_id: UUID
    ) -> None:
        """Raise SectionLockedError when the step's section is still locked.

        Staff of the course and LMS administrators always pass.
        """
        if actor is None or actor.has(Role.LMS_ADMIN):
            return
        async with self.uow_factory() as uow:
            threshold = await uow.engagement.unlock_threshold(course_id)
            if threshold is None:
                return
            if await uow.staff.get(course_id, actor.user_id) is not None:
                return
            course = await uow.courses.get(course_id)
            if course is None or course.live_version_id is None:
                return
            version = await uow.versions.get(course.live_version_id)
            if version is None:
                return
            sections = await self._mastery(
                uow, actor.user_id, version.manifest, threshold
            )
        for section in sections:
            if not section.unlocked and any(
                s.step_id == step_id for s in section.steps
            ):
                raise SectionLockedError(params={"threshold": threshold})

    async def get_settings(
        self, actor: Actor, course_id: UUID
    ) -> EngagementSettingsView:
        """Return the mastery unlock threshold; needs the `review` permission."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            (await staff_access(uow, actor, course_id)).require(REVIEW)
            pct = await uow.engagement.unlock_threshold(course_id)
        return EngagementSettingsView(unlock_threshold_pct=pct)

    async def set_settings(
        self, actor: Actor, course_id: UUID, body: EngagementSettingsView
    ) -> EngagementSettingsView:
        """Set the mastery unlock threshold; needs the `edit` permission."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            (await staff_access(uow, actor, course_id)).require(EDIT)
            await uow.engagement.set_unlock_threshold(
                course_id, body.unlock_threshold_pct
            )
            await uow.commit()
        return body

    # - - - quests - - -

    async def _quest_view(
        self,
        uow: EngagementUnitOfWork,
        quest: QuestRecord,
        course_title: str,
        user_id: UUID | None,
    ) -> EngagementQuestView:
        progress = await uow.engagement.course_progress(
            quest.course_id, quest.goal_kind, quest.starts_on, quest.ends_on
        )
        reached = sum(1 for v in progress.values() if v >= quest.target)
        return EngagementQuestView(
            id=quest.id,
            course_id=quest.course_id,
            course_title=course_title,
            title=quest.title,
            goal_kind=quest.goal_kind,
            target=quest.target,
            my_progress=progress.get(user_id, 0) if user_id else 0,
            class_progress=reached,
            class_target=quest.class_target,
            starts_on=quest.starts_on,
            ends_on=quest.ends_on,
            done=reached >= quest.class_target,
        )

    async def my_quests(self, actor: Actor) -> EngagementQuestListView:
        """Return the running quests of the learner's courses (no ranking)."""
        today = self._today()
        async with self.uow_factory() as uow:
            await self._sync(uow, actor.user_id)
            await uow.commit()
            enrollments = await uow.enrollments.list_for_user(actor.user_id)
            courses = {
                c.id: c
                for c in await uow.courses.get_many([e.course_id for e in enrollments])
            }
            quests = await uow.engagement.quests_of(list(courses), active_on=today)
            items = [
                await self._quest_view(
                    uow, q, courses[q.course_id].title, actor.user_id
                )
                for q in quests
            ]
        return EngagementQuestListView(items=items)

    async def course_quests(
        self, actor: Actor, course_id: UUID
    ) -> EngagementQuestListView:
        """Return every quest of a course for staff with the `review` permission."""
        async with self.uow_factory() as uow:
            course = await load_course(uow, course_id)
            (await staff_access(uow, actor, course_id)).require(REVIEW)
            quests = await uow.engagement.quests_of([course_id])
            items = [await self._quest_view(uow, q, course.title, None) for q in quests]
        return EngagementQuestListView(items=items)

    async def save_quest(
        self,
        actor: Actor,
        course_id: UUID,
        body: EngagementQuestInput,
        quest_id: UUID | None = None,
    ) -> EngagementQuestView:
        """Create or update a quest; needs the `edit` permission."""
        if body.ends_on < body.starts_on or (
            (body.ends_on - body.starts_on).days >= MAX_QUEST_DAYS
        ):
            raise QuestDatesInvalidError(params={"max_days": MAX_QUEST_DAYS})
        async with self.uow_factory() as uow:
            course = await load_course(uow, course_id)
            (await staff_access(uow, actor, course_id)).require(EDIT)
            if quest_id is not None:
                existing = await uow.engagement.get_quest(quest_id)
                if existing is None or existing.course_id != course_id:
                    raise QuestNotFoundError(params={"quest_id": str(quest_id)})
            record = QuestRecord(
                id=quest_id or new_id(),
                course_id=course_id,
                title=body.title.strip(),
                goal_kind=body.goal_kind,
                target=body.target,
                class_target=body.class_target,
                starts_on=body.starts_on,
                ends_on=body.ends_on,
            )
            await uow.engagement.save_quest(record, actor.user_id)
            await uow.commit()
            return await self._quest_view(uow, record, course.title, None)

    async def delete_quest(self, actor: Actor, course_id: UUID, quest_id: UUID) -> None:
        """Delete a quest; needs the `edit` permission."""
        async with self.uow_factory() as uow:
            await load_course(uow, course_id)
            (await staff_access(uow, actor, course_id)).require(EDIT)
            existing = await uow.engagement.get_quest(quest_id)
            if existing is None or existing.course_id != course_id:
                raise QuestNotFoundError(params={"quest_id": str(quest_id)})
            await uow.engagement.delete_quest(quest_id)
            await uow.commit()

    # - - - nudges - - -

    async def list_nudge_candidates(self, day: date) -> list[Nudge]:
        """Return the nudges of a Tashkent day (read-only; notify writes them).

        Due reviews, weekday streaks at risk and quests ending today or tomorrow.
        """
        now = self.clock.now()
        today = day
        nudges: list[Nudge] = []
        async with self.uow_factory() as uow:
            due = await uow.engagement.due_counts(now)
            recent = await uow.engagement.learners_with_recent_xp(
                today - timedelta(days=14)
            )
            for user_id, count in due.items():
                nudges.append(Nudge(user_id, REVIEW_DUE, {"count": count}))
            for user_id in recent:
                days = await uow.engagement.active_days(
                    user_id, today - timedelta(days=HISTORY_DAYS)
                )
                streak = compute_streak(days, today)
                if streak.at_risk:
                    nudges.append(
                        Nudge(user_id, STREAK_AT_RISK, {"streak": streak.current})
                    )
            ending = [
                q
                for q in await uow.engagement.quests_of_all_active(today)
                if (q.ends_on - today).days <= 1
            ]
            for quest in ending:
                progress = await uow.engagement.course_progress(
                    quest.course_id, quest.goal_kind, quest.starts_on, quest.ends_on
                )
                for enrollment in await uow.enrollments.list_for_course(
                    quest.course_id
                ):
                    if progress.get(enrollment.user_id, 0) < quest.target:
                        nudges.append(
                            Nudge(
                                enrollment.user_id,
                                DEADLINE_SOON,
                                {
                                    "quest_id": str(quest.id),
                                    "title": quest.title,
                                    "ends_on": quest.ends_on.isoformat(),
                                },
                            )
                        )
        return nudges
