"""Question bank routes: a bank per subject (EMIS id) split by curriculum topic."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.notebooks.domain.question_bank import (
    BankQuestion,
    Difficulty,
    Origin,
    Visibility,
)
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError
from app.shared.contracts.teacher_ai import QuestionItem

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/teacher/question-bank", tags=["teacher-ai"])

ActorDep = Annotated[Actor, Depends(get_actor)]
ContainerDep = Annotated[Container, Depends(get_container)]


class QuestionBody(BaseModel):
    """One question to store."""

    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=2000)
    options: list[str] = Field(default_factory=list, max_length=10)
    explanation: str | None = Field(default=None, max_length=2000)


class SaveBody(BaseModel):
    """Questions saved to the bank of a topic."""

    topic: str = Field(min_length=1, max_length=255)
    questions: list[QuestionBody] = Field(min_length=1, max_length=100)
    difficulty: Difficulty = "medium"
    visibility: Visibility = "teacher"


class DrawBody(BaseModel):
    """A random test drawn from the bank."""

    topic: str = Field(min_length=1, max_length=255)
    count: int = Field(ge=1, le=100)
    difficulty: Difficulty | None = None
    seed: int | None = None


class VisibilityBody(BaseModel):
    """Share with the subject's teachers, or take it back."""

    visibility: Visibility


class EditBody(BaseModel):
    """The new text of a question."""

    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=2000)
    options: list[str] = Field(default_factory=list, max_length=10)
    explanation: str | None = Field(default=None, max_length=2000)
    difficulty: Difficulty | None = None


class BankQuestionOut(BaseModel):
    """A stored question as the staff app reads it."""

    id: UUID
    topic: str
    question: str
    answer: str
    options: list[str]
    explanation: str | None
    difficulty: Difficulty
    origin: Origin
    visibility: Visibility
    created_at: datetime


class PageOut(BaseModel):
    """One page of questions and the total behind it."""

    items: list[BankQuestionOut]
    total: int


class TopicCountOut(BaseModel):
    """A curriculum topic with the questions the caller sees in it."""

    topic: str
    count: int


class CurriculumTopicOut(BaseModel):
    """A curriculum topic of the subject."""

    topic: str
    grade: int | None


class SaveOut(BaseModel):
    """How many questions were stored and how many were duplicates."""

    saved: int
    skipped: int


def _view(row: BankQuestion) -> BankQuestionOut:
    return BankQuestionOut(
        id=row.id,
        topic=row.topic,
        question=row.question,
        answer=row.answer,
        options=list(row.options),
        explanation=row.explanation,
        difficulty=row.difficulty,
        origin=row.origin,
        visibility=row.visibility,
        created_at=row.created_at,
    )


async def _emis_id(container: Container, subject_id: UUID) -> int:
    emis = await container.academic.schedule.queries.subject_emis_id(subject_id)
    if emis is None:
        raise NotFoundError(params={"subject_id": str(subject_id)})
    return emis


@router.get("/subjects/{subject_id}/topics")
async def topics(
    subject_id: UUID, actor: ActorDep, container: ContainerDep
) -> list[TopicCountOut]:
    """Every topic of the subject with the number of questions the caller sees."""
    emis = await _emis_id(container, subject_id)
    counts = await container.notebooks.question_bank.topics(actor, emis)
    return [TopicCountOut(topic=t, count=n) for t, n in counts.items()]


@router.get("/subjects/{subject_id}/curriculum-topics")
async def curriculum_topics(
    subject_id: UUID, actor: ActorDep, container: ContainerDep
) -> list[CurriculumTopicOut]:
    """The EMIS curriculum topics of the subject, in plan order."""
    emis = await _emis_id(container, subject_id)
    names = await container.notebooks.question_bank.curriculum_topics(actor, emis)
    return [CurriculumTopicOut(topic=t, grade=None) for t in names]


@router.post("/subjects/{subject_id}/questions", status_code=201)
async def save(
    subject_id: UUID, body: SaveBody, actor: ActorDep, container: ContainerDep
) -> SaveOut:
    """Store questions; ones the caller already sees are skipped."""
    emis = await _emis_id(container, subject_id)
    result = await container.notebooks.question_bank.save_generated(
        actor,
        emis_subject_id=emis,
        topic=body.topic,
        questions=[
            QuestionItem(q.question, q.answer, tuple(q.options), q.explanation)
            for q in body.questions
        ],
        difficulty=body.difficulty,
        origin="teacher" if body.visibility == "subject" else "ai",
        visibility=body.visibility,
    )
    return SaveOut(saved=len(result.saved), skipped=len(result.skipped))


@router.post("/subjects/{subject_id}/draw")
async def draw(
    subject_id: UUID, body: DrawBody, actor: ActorDep, container: ContainerDep
) -> list[BankQuestionOut]:
    """A random set of questions without repeats."""
    emis = await _emis_id(container, subject_id)
    rows = await container.notebooks.question_bank.draw(
        actor,
        emis_subject_id=emis,
        topic=body.topic,
        count=body.count,
        difficulty=body.difficulty,
        seed=body.seed,
    )
    return [_view(r) for r in rows]


@router.put("/questions/{question_id}/visibility", status_code=204)
async def set_visibility(
    question_id: UUID, body: VisibilityBody, actor: ActorDep, container: ContainerDep
) -> None:
    """Change who sees a question the caller owns."""
    await container.notebooks.question_bank.set_visibility(
        actor, question_id, body.visibility
    )


@router.get("/subjects/{subject_id}/questions")
async def list_questions(
    subject_id: UUID,
    actor: ActorDep,
    container: ContainerDep,
    topic: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageOut:
    """One page of the questions the caller sees, optionally of one topic."""
    emis = await _emis_id(container, subject_id)
    rows, total = await container.notebooks.question_bank.list_questions(
        actor, emis_subject_id=emis, topic=topic, limit=limit, offset=offset
    )
    return PageOut(items=[_view(r) for r in rows], total=total)


@router.put("/questions/{question_id}")
async def edit_question(
    question_id: UUID, body: EditBody, actor: ActorDep, container: ContainerDep
) -> BankQuestionOut:
    """Rewrite a question the caller owns (an administrator may edit any)."""
    row = await container.notebooks.question_bank.edit(
        actor,
        question_id,
        question=body.question,
        answer=body.answer,
        options=body.options,
        explanation=body.explanation,
        difficulty=body.difficulty,
    )
    return _view(row)


@router.delete("/questions/{question_id}", status_code=204)
async def delete_question(
    question_id: UUID, actor: ActorDep, container: ContainerDep
) -> None:
    """Remove a question the caller owns (an administrator may remove any)."""
    await container.notebooks.question_bank.delete(actor, question_id)
