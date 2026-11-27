"""POST /v1/lms/courses/{cid}/steps/{sid}/blocks:from-questions."""

from typing import Annotated, Any
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.shared.actor import Actor, Role
from app.shared.contracts.teacher_ai import QuestionItem

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/lms/courses/{course_id}", tags=["lms-authoring"])

AuthorDep = Annotated[
    Actor,
    Depends(
        require_roles(
            Role.TEACHER, Role.ADMIN, Role.LMS_ADMIN, Role.LMS_CREATOR, Role.SU
        )
    ),
]


class QuestionBody(BaseModel):
    """One generated question."""

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    options: list[str] = Field(default_factory=list)
    explanation: str | None = None


class QuestionBlocksBody(BaseModel):
    """Questions to turn into one test block of the step."""

    questions: list[QuestionBody] = Field(min_length=1)
    position: int | None = Field(default=None, ge=0)


@router.post("/steps/{step_id}/blocks:from-questions", status_code=201)
async def add_blocks_from_questions(
    course_id: UUID,
    step_id: UUID,
    body: QuestionBlocksBody,
    actor: AuthorDep,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    """Add a test block built from the questions at the position (or the end)."""
    items = [
        QuestionItem(q.question, q.answer, tuple(q.options), q.explanation)
        for q in body.questions
    ]
    block: dict[str, Any] = await container.lms_authoring.add_blocks_from_questions(
        actor, course_id, step_id, items, body.position
    )
    return block
