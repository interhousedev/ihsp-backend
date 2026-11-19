"""Profile details routes: interests, quiz answers, completion, document process."""

from typing import Any, Literal

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.document_process import ProcessStep
from app.modules.admission.application.profile_details import DetailsOverview
from app.modules.admission.domain.profile_details import (
    MAX_QUESTIONS,
    QuizAnswers,
)

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

AnswerT = bool | int | str | list[str]
QuizT = Literal["career", "algorithm"]


class InterestsIO(BaseModel):
    """Fields of interest and service interests (vocabulary keys)."""

    fields: list[str] = Field(default_factory=list, max_length=40)
    services: list[str] = Field(default_factory=list, max_length=40)


class MissingDetailOut(BaseModel):
    """A profile detail still to fill in."""

    key: str
    label: str


class ProfileDetailsOut(BaseModel):
    """Interests, three words and the completion of the profile."""

    interests: InterestsIO
    three_words: list[str]
    completion_percent: int
    missing: list[MissingDetailOut]

    @classmethod
    def of(cls, o: DetailsOverview) -> "ProfileDetailsOut":
        """Map the overview."""
        return cls(
            interests=InterestsIO(
                fields=list(o.interests.fields), services=list(o.interests.services)
            ),
            three_words=list(o.three_words),
            completion_percent=o.percent,
            missing=[MissingDetailOut(key=m.key, label=m.label) for m in o.missing],
        )


class QuizAnswersIO(BaseModel):
    """Answers of a quiz by question id; multi-choice answers are lists."""

    answers: dict[str, AnswerT] = Field(default_factory=dict, max_length=MAX_QUESTIONS)
    completed: bool = False

    @classmethod
    def of(cls, q: QuizAnswers) -> "QuizAnswersIO":
        """Map the stored answers."""
        return cls(answers=dict(q.answers), completed=q.completed)


class ProcessStepOut(BaseModel):
    """One step of the document issuing process."""

    key: str
    title: str
    issuer: str
    description: str
    lead_days_min: int
    lead_days_max: int
    status: Literal["not_started", "requested", "ready", "not_tracked"]

    @classmethod
    def of(cls, s: ProcessStep) -> "ProcessStepOut":
        """Map the step."""
        return cls.model_validate(s, from_attributes=True)


class DocumentProcessOut(BaseModel):
    """Steps in order, with the caller's own status."""

    steps: list[ProcessStepOut]


async def get_details(
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: str | None = Header(default=None),
) -> ProfileDetailsOut:
    """My interests, three words, completion percent and missing details."""
    done = await container.admission.profile_details.overview(
        ctx, _locale(accept_language)
    )
    return ProfileDetailsOut.of(done)


async def put_interests(
    body: InterestsIO, container: ContainerDep, ctx: AdmissionCtx
) -> InterestsIO:
    """Replace my fields of interest and service interests."""
    saved = await container.admission.profile_details.put_interests(
        ctx, body.fields, body.services
    )
    return InterestsIO(fields=list(saved.fields), services=list(saved.services))


async def get_quiz(
    quiz: QuizT, container: ContainerDep, ctx: StudentCtx
) -> QuizAnswersIO:
    """My stored answers of a quiz."""
    return QuizAnswersIO.of(
        await container.admission.profile_details.get_quiz(ctx, quiz)
    )


async def put_quiz(
    quiz: QuizT, body: QuizAnswersIO, container: ContainerDep, ctx: StudentCtx
) -> QuizAnswersIO:
    """Replace my answers of a quiz."""
    saved = await container.admission.profile_details.put_quiz(
        ctx, quiz, body.answers, body.completed
    )
    return QuizAnswersIO.of(saved)


async def document_process(
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: str | None = Header(default=None),
) -> DocumentProcessOut:
    """Who issues each document, typical lead times and my status."""
    steps = await container.admission.document_process.steps(
        ctx, _locale(accept_language)
    )
    return DocumentProcessOut(steps=[ProcessStepOut.of(s) for s in steps])


def _route(path: str, endpoint: Any, method: str, op: str, model: Any) -> None:
    router.add_api_route(
        path,
        endpoint,
        methods=[method],
        operation_id=f"admission_{op}",
        response_model=model,
    )


_route(
    "/me/profile/details", get_details, "GET", "profile_details_get", ProfileDetailsOut
)
_route(
    "/me/profile/interests", put_interests, "PUT", "profile_interests_put", InterestsIO
)
_route("/me/quizzes/{quiz}", get_quiz, "GET", "quiz_answers_get", QuizAnswersIO)
_route("/me/quizzes/{quiz}", put_quiz, "PUT", "quiz_answers_put", QuizAnswersIO)
_route(
    "/document-process", document_process, "GET", "document_process", DocumentProcessOut
)
