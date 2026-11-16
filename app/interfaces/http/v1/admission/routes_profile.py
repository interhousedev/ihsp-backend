"""Profile, three words and alignment routes (`/v1/admission/*`)."""

import dataclasses
import datetime as dt
from typing import Any
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.modules.admission.application.profile import ProfileView
from app.modules.admission.application.profile_alignment import AlignmentResult
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.profile_words import WordsState

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class ProfileOut(BaseModel):
    """Visible answers and the resume point."""

    student_id: UUID
    account_kind: str
    stage: str
    question_set_version: str
    answers: dict[str, Any]
    next_question: str | None
    missing_required: list[str]
    setup_completed: bool
    lock_version: int

    @classmethod
    def of(cls, v: ProfileView) -> "ProfileOut":
        """Map the application view."""
        data = dataclasses.asdict(v)
        return cls(**{**data, "missing_required": list(v.missing_required)})


class ProfilePutIn(BaseModel):
    """Answers to save; `lock_version` is required once a profile exists."""

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, Any]
    lock_version: int | None = None


class CandidateOut(BaseModel):
    """One suggested word with its evidence."""

    word: str
    reason: str
    evidence_refs: list[str]


class WordsOut(BaseModel):
    """Confirmed words and the last suggestions."""

    words: list[str]
    candidates: list[CandidateOut]
    source: str
    version: int
    confirmed_at: dt.datetime | None
    lock_version: int

    @classmethod
    def of(cls, s: WordsState) -> "WordsOut":
        """Map the state."""
        return cls(
            words=list(s.words),
            candidates=[
                CandidateOut(
                    word=c["word"],
                    reason=c.get("reason", ""),
                    evidence_refs=list(c.get("evidence_refs", [])),
                )
                for c in s.candidates
            ],
            source=s.source,
            version=s.version,
            confirmed_at=s.confirmed_at,
            lock_version=s.lock_version,
        )


class WordsPutIn(BaseModel):
    """Exactly three words and the lock version that was read."""

    model_config = ConfigDict(extra="forbid")

    words: list[str]
    lock_version: int


class AlignmentOut(BaseModel):
    """The alignment map; no grade when `safety_flag` is safeguarding."""

    overall: str | None
    grades: dict[str, Any]
    payload: dict[str, Any]
    safety_flag: str
    message_key: str | None
    words_version: int | None
    stale: bool
    created_at: dt.datetime | None

    @classmethod
    def of(cls, r: AlignmentResult) -> "AlignmentOut":
        """Map the result."""
        v = r.review
        return cls(
            overall=v.overall,
            grades=v.grades,
            payload=v.payload,
            safety_flag=v.safety_flag,
            message_key=v.payload.get("message_key"),
            words_version=v.words_version,
            stale=r.stale,
            created_at=v.created_at,
        )


async def get_my_profile(container: ContainerDep, ctx: AdmissionCtx) -> ProfileOut:
    """Return my profile answers and where to resume."""
    return ProfileOut.of(await container.admission.profile.get(ctx, ctx.user_id))


async def put_my_profile(
    body: ProfilePutIn, container: ContainerDep, ctx: AdmissionCtx
) -> ProfileOut:
    """Save answers (partial saves allowed)."""
    view = await container.admission.profile.save(ctx, body.answers, body.lock_version)
    return ProfileOut.of(view)


async def get_student_profile(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ProfileOut:
    """Return a student's profile as the caller may see it."""
    return ProfileOut.of(await container.admission.profile.get(ctx, student_id))


async def get_my_words(container: ContainerDep, ctx: AdmissionCtx) -> WordsOut:
    """Return my three words and suggestions."""
    return WordsOut.of(await container.admission.words.get(ctx, ctx.user_id))


async def put_my_words(
    body: WordsPutIn, container: ContainerDep, ctx: AdmissionCtx
) -> WordsOut:
    """Confirm the three words (creates a new version)."""
    state = await container.admission.words.set(ctx, body.words, body.lock_version)
    return WordsOut.of(state)


async def suggest_my_words(container: ContainerDep, ctx: AdmissionCtx) -> WordsOut:
    """Ask the AI for eight candidate words."""
    return WordsOut.of(await container.admission.words.suggest(ctx))


async def get_student_words(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> WordsOut:
    """Return a student's words."""
    return WordsOut.of(await container.admission.words.get(ctx, student_id))


async def run_my_alignment(container: ContainerDep, ctx: AdmissionCtx) -> AlignmentOut:
    """Run (or reuse) the alignment map."""
    return AlignmentOut.of(await container.admission.alignment.run(ctx))


async def get_my_alignment(container: ContainerDep, ctx: AdmissionCtx) -> AlignmentOut:
    """Return my latest alignment map."""
    return await _latest(container, ctx, ctx.user_id)


async def get_student_alignment(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> AlignmentOut:
    """Return a student's latest alignment map."""
    return await _latest(container, ctx, student_id)


async def _latest(
    container: ContainerDep, ctx: AdmissionCtx, student_id: UUID
) -> AlignmentOut:
    result = await container.admission.alignment.latest(ctx, student_id)
    if result is None:
        raise AdmissionNotFoundError()
    return AlignmentOut.of(result)


for _path, _fn, _method, _model, _op in (
    ("/me/profile", get_my_profile, "GET", ProfileOut, "admission_get_my_profile"),
    ("/me/profile", put_my_profile, "PUT", ProfileOut, "admission_put_my_profile"),
    ("/me/words", get_my_words, "GET", WordsOut, "admission_get_my_words"),
    ("/me/words", put_my_words, "PUT", WordsOut, "admission_put_my_words"),
    (
        "/me/words/suggest",
        suggest_my_words,
        "POST",
        WordsOut,
        "admission_suggest_my_words",
    ),
    (
        "/me/alignment",
        run_my_alignment,
        "POST",
        AlignmentOut,
        "admission_run_my_alignment",
    ),
    (
        "/me/alignment",
        get_my_alignment,
        "GET",
        AlignmentOut,
        "admission_get_my_alignment",
    ),
    (
        "/students/{student_id}/profile",
        get_student_profile,
        "GET",
        ProfileOut,
        "admission_get_student_profile",
    ),
    (
        "/students/{student_id}/words",
        get_student_words,
        "GET",
        WordsOut,
        "admission_get_student_words",
    ),
    (
        "/students/{student_id}/alignment",
        get_student_alignment,
        "GET",
        AlignmentOut,
        "admission_get_student_alignment",
    ),
):
    router.add_api_route(
        _path,
        _fn,
        methods=[_method],
        response_model=_model,
        operation_id=_op,
    )
