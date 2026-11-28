"""Teacher AI tools over HTTP: the same `TeacherAiTools` the MCP server uses."""

from dataclasses import asdict
from typing import Annotated, Any
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.shared.actor import Actor, Role
from app.shared.contracts.teacher_ai import (
    CheckAuthorshipArgs,
    CheckWorkArgs,
    GenerateHandoutArgs,
    GenerateLessonPlanArgs,
    GenerateQuestionsArgs,
    HandoutLength,
    QuestionType,
    RegisterPlanTemplateArgs,
    TeacherAiTools,
)

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

router = APIRouter(prefix="/v1/teacher/ai", tags=["teacher-ai"])

_TEXT = 20_000


def _staff(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
    actor.require(Role.TEACHER, Role.ADMIN)
    return actor


Staff = Annotated[Actor, Depends(_staff)]


def _tools(container: Annotated[Container, Depends(get_container)]) -> TeacherAiTools:
    tools = container.teacher_ai_tools
    assert tools is not None
    return tools


Tools = Annotated[TeacherAiTools, Depends(_tools)]


class QuestionsBody(BaseModel):
    """Questions for a topic; the output lands in the subject notebook."""

    topic: str = Field(min_length=1, max_length=500)
    count: int = Field(default=10, ge=1, le=30)
    question_type: QuestionType = "mixed"
    level: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, max_length=8)
    source_text: str | None = Field(default=None, max_length=_TEXT)
    subject_id: UUID
    group_id: UUID | None = None


class HandoutBody(BaseModel):
    """A handout on a topic."""

    topic: str = Field(min_length=1, max_length=500)
    level: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, max_length=8)
    length: HandoutLength = "medium"
    source_text: str | None = Field(default=None, max_length=_TEXT)
    subject_id: UUID
    group_id: UUID | None = None


class WorkCheckBody(BaseModel):
    """Pasted work with a destination, or a submission id."""

    assignment: str | None = Field(default=None, max_length=_TEXT)
    student_work: str | None = Field(default=None, max_length=_TEXT)
    submission_id: UUID | None = None
    rubric: str | None = Field(default=None, max_length=_TEXT)
    max_score: float | None = Field(default=None, gt=0, le=1000)
    language: str | None = Field(default=None, max_length=8)
    subject_id: UUID | None = None
    group_id: UUID | None = None

    @model_validator(mode="after")
    def _one_form(self) -> "WorkCheckBody":
        pasted = bool(self.assignment and self.student_work)
        if pasted == (self.submission_id is not None):
            raise ValueError("send either submission_id or assignment and work")
        if pasted and self.subject_id is None:
            raise ValueError("subject_id is required")
        return self


class AuthorshipBody(BaseModel):
    """A text or a submission to judge."""

    text: str | None = Field(default=None, max_length=_TEXT)
    submission_id: UUID | None = None
    context: str | None = Field(default=None, max_length=2000)
    language: str | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def _one_form(self) -> "AuthorshipBody":
        if bool(self.text) == (self.submission_id is not None):
            raise ValueError("send either submission_id or text")
        return self


class LessonPlanBody(BaseModel):
    """A lesson plan."""

    topic: str = Field(min_length=1, max_length=500)
    lesson_id: UUID | None = None
    template_id: UUID | None = None
    duration_minutes: int = Field(default=45, ge=10, le=240)
    language: str | None = Field(default=None, max_length=8)
    notes: str | None = Field(default=None, max_length=_TEXT)
    subject_id: UUID
    group_id: UUID | None = None


class TemplateBody(BaseModel):
    """A lesson plan template."""

    name: str = Field(min_length=1, max_length=200)
    template: str | None = Field(default=None, max_length=_TEXT)
    description: str | None = Field(default=None, max_length=1000)
    file_id: UUID | None = None


@router.post("/questions")
async def questions(body: QuestionsBody, actor: Staff, ai: Tools) -> Any:
    """Generate questions."""
    return asdict(
        await ai.generate_questions(actor, GenerateQuestionsArgs(**body.model_dump()))
    )


@router.post("/handout")
async def handout(body: HandoutBody, actor: Staff, ai: Tools) -> Any:
    """Generate a handout."""
    return asdict(
        await ai.generate_handout(actor, GenerateHandoutArgs(**body.model_dump()))
    )


@router.post("/work-check")
async def work_check(body: WorkCheckBody, actor: Staff, ai: Tools) -> Any:
    """Check a student's work, pasted or by submission."""
    data = body.model_dump()
    data["assignment"] = data["assignment"] or ""
    data["student_work"] = data["student_work"] or ""
    return asdict(await ai.check_work(actor, CheckWorkArgs(**data)))


@router.post("/authorship-check")
async def authorship_check(body: AuthorshipBody, actor: Staff, ai: Tools) -> Any:
    """Estimate machine authorship."""
    data = body.model_dump()
    data["text"] = data["text"] or ""
    return asdict(await ai.check_ai_authorship(actor, CheckAuthorshipArgs(**data)))


@router.post("/lesson-plan")
async def lesson_plan(body: LessonPlanBody, actor: Staff, ai: Tools) -> Any:
    """Generate a lesson plan."""
    return asdict(
        await ai.generate_lesson_plan(
            actor, GenerateLessonPlanArgs(**body.model_dump())
        )
    )


@router.get("/plan-templates")
async def list_templates(actor: Staff, ai: Tools) -> Any:
    """The teacher's plan templates."""
    return [asdict(t) for t in await ai.list_plan_templates(actor)]


@router.post("/plan-templates")
async def register_template(body: TemplateBody, actor: Staff, ai: Tools) -> Any:
    """Store a plan template."""
    return asdict(
        await ai.register_plan_template(
            actor, RegisterPlanTemplateArgs(**body.model_dump())
        )
    )
