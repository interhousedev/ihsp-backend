"""Save generated questions to the bank and draw tests from it."""

import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from uuid import UUID

from app.modules.notebooks.domain.question_bank import (
    BankQuestion,
    Difficulty,
    Origin,
    Visibility,
    question_key,
)
from app.modules.notebooks.ports.question_bank import (
    QuestionBankStore,
    SubjectTeaching,
    SubjectTopicCatalog,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)
from app.shared.clock import Clock
from app.shared.contracts.teacher_ai import QuestionItem
from app.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class SaveResult:
    """What was stored and which questions were already there."""

    saved: tuple[BankQuestion, ...]
    skipped: tuple[QuestionItem, ...]


def _require_staff(actor: Actor) -> None:
    if not (actor.has(Role.TEACHER) or actor.has(Role.ADMIN)):
        raise ForbiddenError(params={"roles": ["teacher", "admin"]})


class QuestionBankService:
    """The bank of one EMIS subject, split by the topics of its curriculum."""

    def __init__(
        self,
        store: QuestionBankStore,
        clock: Clock,
        catalog: SubjectTopicCatalog,
        scope: SubjectTeaching,
    ) -> None:
        """Bind the store, the clock, the topic directory and the teaching check."""
        self.store = store
        self.clock = clock
        self.catalog = catalog
        self.scope = scope

    async def _access(self, actor: Actor, emis_subject_id: int) -> None:
        _require_staff(actor)
        if not await self.scope.teaches(actor, emis_subject_id):
            raise ForbiddenError(params={"emis_subject_id": emis_subject_id})

    async def _catalogue(self, emis_subject_id: int) -> tuple[str, ...]:
        topics = await self.catalog.topics(emis_subject_id)
        if topics is None:
            raise NotFoundError(params={"emis_subject_id": emis_subject_id})
        return topics

    async def _checked_topic(self, emis_subject_id: int, topic: str) -> str:
        known = await self._catalogue(emis_subject_id)
        clean = topic.strip()
        if not clean or clean not in known:
            raise ValidationFailedError(params={"field": "topic"})
        return clean

    async def save_generated(
        self,
        actor: Actor,
        *,
        emis_subject_id: int,
        topic: str,
        questions: Sequence[QuestionItem],
        difficulty: Difficulty = "medium",
        origin: Origin = "ai",
        visibility: Visibility = "teacher",
    ) -> SaveResult:
        """Store the questions, skipping those the actor already sees."""
        await self._access(actor, emis_subject_id)
        if not questions:
            raise ValidationFailedError(params={"field": "questions"})
        clean = await self._checked_topic(emis_subject_id, topic)
        seen = {
            question_key(text)
            for _, text in await self.store.visible_texts(
                emis_subject_id, clean, actor.user_id
            )
        }
        saved: list[BankQuestion] = []
        skipped: list[QuestionItem] = []
        for item in questions:
            key = question_key(item.question)
            if key in seen:
                skipped.append(item)
                continue
            seen.add(key)
            row = BankQuestion(
                id=new_id(),
                owner_id=actor.user_id,
                emis_subject_id=emis_subject_id,
                topic=clean,
                question=item.question,
                answer=item.answer,
                options=tuple(item.options),
                explanation=item.explanation,
                difficulty=difficulty,
                origin=origin,
                visibility=visibility,
                created_at=self.clock.now(),
            )
            saved.append(row)
        await self.store.add_many(saved)
        return SaveResult(tuple(saved), tuple(skipped))

    async def draw(
        self,
        actor: Actor,
        *,
        emis_subject_id: int,
        topic: str,
        count: int,
        difficulty: Difficulty | None = None,
        seed: int | None = None,
    ) -> list[BankQuestion]:
        """A random set without repeats; the same seed gives the same set."""
        await self._access(actor, emis_subject_id)
        if count < 1:
            raise ValidationFailedError(params={"field": "count"})
        clean = await self._checked_topic(emis_subject_id, topic)
        ids = await self.store.visible_ids(
            emis_subject_id, clean, actor.user_id, difficulty
        )
        random.Random(seed).shuffle(ids)
        return await self.store.get_many(ids[:count])

    async def curriculum_topics(
        self, actor: Actor, emis_subject_id: int
    ) -> tuple[str, ...]:
        """The subject's EMIS curriculum topics in plan order."""
        await self._access(actor, emis_subject_id)
        return await self._catalogue(emis_subject_id)

    async def topics(self, actor: Actor, emis_subject_id: int) -> dict[str, int]:
        """Every catalogue topic with the number of questions the actor sees."""
        await self._access(actor, emis_subject_id)
        known = await self._catalogue(emis_subject_id)
        counts = await self.store.count_by_topic(emis_subject_id, actor.user_id)
        return {topic: counts.get(topic, 0) for topic in known}

    async def set_visibility(
        self, actor: Actor, question_id: UUID, visibility: Visibility
    ) -> None:
        """Share a question with the subject's teachers, or take it back."""
        _require_staff(actor)
        row = await self.store.get(question_id)
        if row is None or row.owner_id != actor.user_id:
            raise NotFoundError(params={"question_id": str(question_id)})
        await self.store.replace(replace(row, visibility=visibility))

    async def list_questions(
        self,
        actor: Actor,
        *,
        emis_subject_id: int,
        topic: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[BankQuestion], int]:
        """One page of the questions the actor sees (newest first) and the total."""
        await self._access(actor, emis_subject_id)
        if limit < 1 or offset < 0:
            raise ValidationFailedError(params={"field": "page"})
        clean = (
            None if topic is None else await self._checked_topic(emis_subject_id, topic)
        )
        if clean is None:
            await self._catalogue(emis_subject_id)
        viewer = None if actor.has(Role.ADMIN) else actor.user_id
        return await self.store.page(emis_subject_id, clean, viewer, limit, offset)

    async def _owned(self, actor: Actor, question_id: UUID) -> BankQuestion:
        _require_staff(actor)
        row = await self.store.get(question_id)
        if row is None or not (row.owner_id == actor.user_id or actor.has(Role.ADMIN)):
            raise NotFoundError(params={"question_id": str(question_id)})
        return row

    async def edit(
        self,
        actor: Actor,
        question_id: UUID,
        *,
        question: str,
        answer: str,
        options: Sequence[str] = (),
        explanation: str | None = None,
        difficulty: Difficulty | None = None,
    ) -> BankQuestion:
        """Rewrite a question; its owner or an administrator only."""
        row = await self._owned(actor, question_id)
        if not question.strip() or not answer.strip():
            raise ValidationFailedError(params={"field": "question"})
        new_key = question_key(question)
        if new_key != question_key(row.question) and any(
            qid != row.id and question_key(text) == new_key
            for qid, text in await self.store.visible_texts(
                row.emis_subject_id, row.topic, actor.user_id
            )
        ):
            raise ConflictError(params={"field": "question"})
        updated = replace(
            row,
            question=question.strip(),
            answer=answer.strip(),
            options=tuple(options),
            explanation=explanation,
            difficulty=difficulty or row.difficulty,
        )
        await self.store.replace(updated)
        return updated

    async def delete(self, actor: Actor, question_id: UUID) -> None:
        """Remove a question; its owner or an administrator only."""
        row = await self._owned(actor, question_id)
        await self.store.delete(row.id)
