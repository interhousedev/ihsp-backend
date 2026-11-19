"""Career exploration: inventory, professions, majors and minors, spike; voice."""

import datetime as dt
from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admission.deps import (
    AdmissionCtx,
    AnyContext,
    ContainerDep,
    StudentCtx,
)
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.study_focus import StudyFocus
from app.modules.admission.application.voice import VoiceService
from app.modules.admission.domain.career import (
    ANSWER_MAX,
    CODE_MAX,
    EVIDENCE_MAX,
    GAPS_MAX,
    MAJORS_MAX,
    MINORS_MAX,
    REASON_MAX,
    SHORTLIST_MAX,
    SUMMARY_MAX,
    TITLE_MAX,
    CareerMajor,
    CareerPlan,
    CareerQuestion,
    CareerSection,
)
from app.modules.admission.domain.errors import VoiceTooLargeError
from app.shared.contracts.ai import AiProviderError

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Section = CareerSection
Lang = Annotated[str | None, Header(alias="Accept-Language")]
_MB = 1024 * 1024


class QuestionOut(BaseModel):
    """One inventory question with its text in every language."""

    id: UUID
    section: Section
    prompt: dict[str, str]
    sort_order: int
    active: bool

    @classmethod
    def of(cls, q: CareerQuestion) -> "QuestionOut":
        """From the domain object."""
        return cls(
            id=q.id,
            section=q.section,
            prompt=q.prompt,
            sort_order=q.sort_order,
            active=q.active,
        )


class QuestionsOut(BaseModel):
    """The inventory, in order."""

    items: list[QuestionOut]


class QuestionIn(BaseModel):
    """A question to add or replace (administrators and counselors)."""

    section: Section
    prompt: dict[str, str]
    sort_order: int = Field(default=0, ge=0, le=10_000)
    active: bool = True


class MajorOut(BaseModel):
    """One major of the taxonomy."""

    id: UUID
    code: str
    area: str
    name: dict[str, str]
    minor_ok: bool
    sort_order: int
    active: bool

    @classmethod
    def of(cls, m: CareerMajor) -> "MajorOut":
        """From the domain object."""
        return cls(
            id=m.id,
            code=m.code,
            area=m.area,
            name=m.name,
            minor_ok=m.minor_ok,
            sort_order=m.sort_order,
            active=m.active,
        )


class MajorsOut(BaseModel):
    """The taxonomy, in order."""

    items: list[MajorOut]


class MajorIn(BaseModel):
    """A major to add or replace (administrators and counselors)."""

    code: str = Field(min_length=1, max_length=CODE_MAX, pattern=r"^[a-z0-9_]+$")
    area: str = Field(min_length=1, max_length=48)
    name: dict[str, str]
    minor_ok: bool = True
    sort_order: int = Field(default=0, ge=0, le=10_000)
    active: bool = True


class ProfessionOut(BaseModel):
    """A suggested profession; shortlisted ones stay across suggestions."""

    title: str
    reason: str
    shortlisted: bool


class FitOut(BaseModel):
    """How well a major fits, 0 to 100."""

    code: str
    score: int
    reason: str


class EvidenceOut(BaseModel):
    """An item that supports the spike."""

    item_id: UUID
    note: str


class SpikeOut(BaseModel):
    """The spike; `confirmed_at` is null while it is an AI draft."""

    title: str
    summary: str
    evidence: list[EvidenceOut]
    gaps: list[str]
    confirmed_at: dt.datetime | None


class StudyFocusOut(BaseModel):
    """The field of study from the plan, the career quiz and the setup answer."""

    field_ids: list[str]
    labels: list[str]


class CareerPlanOut(BaseModel):
    """A student's career exploration."""

    student_id: UUID
    answers: dict[str, str]
    professions: list[ProfessionOut]
    majors: list[str]
    minors: list[str]
    fit: list[FitOut]
    spike: SpikeOut | None
    study_focus: StudyFocusOut
    lock_version: int

    @classmethod
    def of(cls, p: CareerPlan, focus: StudyFocus, locale: str) -> "CareerPlanOut":
        """From the domain object."""
        spike = None
        if p.spike is not None:
            spike = SpikeOut(
                title=p.spike.title,
                summary=p.spike.summary,
                evidence=[
                    EvidenceOut(item_id=e.item_id, note=e.note)
                    for e in p.spike.evidence
                ],
                gaps=list(p.spike.gaps),
                confirmed_at=p.spike.confirmed_at,
            )
        return cls(
            student_id=p.student_id,
            answers=p.answers,
            professions=[
                ProfessionOut(title=x.title, reason=x.reason, shortlisted=x.shortlisted)
                for x in p.professions
            ],
            majors=p.majors,
            minors=p.minors,
            fit=[FitOut(code=f.code, score=f.score, reason=f.reason) for f in p.fit],
            spike=spike,
            study_focus=StudyFocusOut(
                field_ids=list(focus.field_ids), labels=list(focus.labels(locale))
            ),
            lock_version=p.lock_version,
        )


class AnswersIn(BaseModel):
    """Answers by question id."""

    answers: dict[str, Annotated[str, Field(max_length=ANSWER_MAX)]] = Field(
        max_length=64
    )
    lock_version: int = Field(ge=0)


class ShortlistIn(BaseModel):
    """The professions the student keeps."""

    titles: list[Annotated[str, Field(max_length=TITLE_MAX)]] = Field(
        max_length=SHORTLIST_MAX
    )
    lock_version: int = Field(ge=0)


class ChoiceIn(BaseModel):
    """Chosen majors and minors by code."""

    majors: list[str] = Field(max_length=MAJORS_MAX)
    minors: list[str] = Field(max_length=MINORS_MAX)
    lock_version: int = Field(ge=0)


class EvidenceIn(BaseModel):
    """An own item and why it supports the spike."""

    item_id: UUID
    note: str = Field(min_length=1, max_length=REASON_MAX)


class SpikeIn(BaseModel):
    """The spike the student confirms."""

    title: str = Field(min_length=1, max_length=TITLE_MAX)
    summary: str = Field(min_length=1, max_length=SUMMARY_MAX)
    evidence: list[EvidenceIn] = Field(max_length=EVIDENCE_MAX)
    gaps: list[Annotated[str, Field(min_length=1, max_length=REASON_MAX)]] = Field(
        max_length=GAPS_MAX
    )
    lock_version: int = Field(ge=0)


class TranscriptOut(BaseModel):
    """The text of a voice answer (the audio is not kept)."""

    text: str


class SpeechIn(BaseModel):
    """The question to read aloud."""

    question_id: UUID


async def _plan_out(
    container: ContainerDep, plan: CareerPlan, accept_language: Lang
) -> CareerPlanOut:
    """The plan with the study focus read for its owner (already authorized)."""
    focus = await container.admission.career.focus(plan.student_id)
    return CareerPlanOut.of(plan, focus, _locale(accept_language))


async def get_career(
    container: ContainerDep, ctx: StudentCtx, accept_language: Lang = None
) -> CareerPlanOut:
    """My career plan."""
    plan = await container.admission.career.plan(ctx, ctx.user_id)
    return await _plan_out(container, plan, accept_language)


async def get_student_career(
    student_id: UUID,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: Lang = None,
) -> CareerPlanOut:
    """A student's career plan (staff in scope or the student)."""
    plan = await container.admission.career.plan(ctx, student_id)
    return await _plan_out(container, plan, accept_language)


async def list_questions(container: ContainerDep, ctx: AdmissionCtx) -> QuestionsOut:
    """The active inventory questions."""
    rows = await container.admission.career.questions()
    return QuestionsOut(items=[QuestionOut.of(q) for q in rows])


async def list_majors(container: ContainerDep, ctx: AdmissionCtx) -> MajorsOut:
    """The active majors."""
    rows = await container.admission.career.majors()
    return MajorsOut(items=[MajorOut.of(m) for m in rows])


async def put_answers(
    body: AnswersIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: Lang = None,
) -> CareerPlanOut:
    """Save my inventory answers."""
    plan = await container.admission.career.save_answers(
        ctx, body.answers, body.lock_version
    )
    return await _plan_out(container, plan, accept_language)


async def put_shortlist(
    body: ShortlistIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: Lang = None,
) -> CareerPlanOut:
    """Keep up to five suggested professions."""
    plan = await container.admission.career.shortlist(
        ctx, body.titles, body.lock_version
    )
    return await _plan_out(container, plan, accept_language)


async def put_choice(
    body: ChoiceIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: Lang = None,
) -> CareerPlanOut:
    """Choose majors and minors from the taxonomy."""
    plan = await container.admission.career.choose(
        ctx, body.majors, body.minors, body.lock_version
    )
    return await _plan_out(container, plan, accept_language)


async def put_spike(
    body: SpikeIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: Lang = None,
) -> CareerPlanOut:
    """Confirm my spike."""
    plan = await container.admission.career.confirm_spike(
        ctx,
        body.title,
        body.summary,
        [(e.item_id, e.note) for e in body.evidence],
        body.gaps,
        body.lock_version,
    )
    return await _plan_out(container, plan, accept_language)


async def suggest_professions(
    container: ContainerDep, ctx: AdmissionCtx, accept_language: Lang = None
) -> CareerPlanOut:
    """Suggest professions with AI (consent and a weekly limit apply)."""
    ai = container.admission.career_ai
    plan = await ai.professions(ctx, _locale(accept_language))
    return await _plan_out(container, plan, accept_language)


async def suggest_fit(
    container: ContainerDep, ctx: AdmissionCtx, accept_language: Lang = None
) -> CareerPlanOut:
    """Rank the majors with AI (consent and a weekly limit apply)."""
    ai = container.admission.career_ai
    plan = await ai.majors_fit(ctx, _locale(accept_language))
    return await _plan_out(container, plan, accept_language)


async def suggest_spike(
    container: ContainerDep, ctx: AdmissionCtx, accept_language: Lang = None
) -> CareerPlanOut:
    """Draft my spike with AI (consent and a weekly limit apply)."""
    ai = container.admission.career_ai
    plan = await ai.spike(ctx, _locale(accept_language))
    return await _plan_out(container, plan, accept_language)


async def admin_questions(container: ContainerDep, ctx: AnyContext) -> QuestionsOut:
    """Every question, inactive ones too (administrators and counselors)."""
    container.admission.career.require_editor(ctx)
    rows = await container.admission.career.questions(include_inactive=True)
    return QuestionsOut(items=[QuestionOut.of(q) for q in rows])


async def admin_create_question(
    body: QuestionIn, container: ContainerDep, ctx: AnyContext
) -> QuestionOut:
    """Add a question (administrators and counselors)."""
    saved = await container.admission.career.save_question(
        ctx, None, body.section, body.prompt, body.sort_order, body.active
    )
    return QuestionOut.of(saved)


async def admin_put_question(
    question_id: UUID, body: QuestionIn, container: ContainerDep, ctx: AnyContext
) -> QuestionOut:
    """Replace a question (administrators and counselors)."""
    saved = await container.admission.career.save_question(
        ctx, question_id, body.section, body.prompt, body.sort_order, body.active
    )
    return QuestionOut.of(saved)


async def admin_majors(container: ContainerDep, ctx: AnyContext) -> MajorsOut:
    """Every major, inactive ones too (administrators and counselors)."""
    container.admission.career.require_editor(ctx)
    rows = await container.admission.career.majors(include_inactive=True)
    return MajorsOut(items=[MajorOut.of(m) for m in rows])


async def admin_create_major(
    body: MajorIn, container: ContainerDep, ctx: AnyContext
) -> MajorOut:
    """Add a major (administrators and counselors)."""
    saved = await container.admission.career.save_major(ctx, None, **body.model_dump())
    return MajorOut.of(saved)


async def admin_put_major(
    major_id: UUID, body: MajorIn, container: ContainerDep, ctx: AnyContext
) -> MajorOut:
    """Replace a major (administrators and counselors)."""
    saved = await container.admission.career.save_major(
        ctx, major_id, **body.model_dump()
    )
    return MajorOut.of(saved)


def _voice(container: ContainerDep) -> VoiceService:
    voice = container.admission.voice
    if voice is None:
        raise AiProviderError()
    return voice


async def transcribe(
    request: Request,
    container: ContainerDep,
    ctx: AdmissionCtx,
    duration_seconds: Annotated[float, Query(ge=0, le=3600)],
    accept_language: Lang = None,
) -> TranscriptOut:
    """Transcribe a voice answer sent as the raw body (audio/webm, ogg, mp4, wav).

    The body is read into memory up to the size cap and dropped after the call;
    a daily limit applies.
    """
    voice = _voice(container)
    cap = await voice.max_bytes(ctx.user_id)
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > cap:
        raise VoiceTooLargeError(params={"max_mb": round(cap / _MB, 1)})
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > cap:
            raise VoiceTooLargeError(params={"max_mb": round(cap / _MB, 1)})
    text = await voice.transcribe(
        ctx, bytes(data), duration_seconds, _locale(accept_language)
    )
    return TranscriptOut(text=text)


async def speak(
    body: SpeechIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: Lang = None,
) -> Response:
    """Read an inventory question aloud (WAV)."""
    audio = await _voice(container).speak(
        ctx, body.question_id, _locale(accept_language)
    )
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=3600"},
    )


for path, endpoint, method, op in (
    ("/career", get_career, "GET", "get"),
    ("/students/{student_id}/career", get_student_career, "GET", "get_student"),
    ("/career/answers", put_answers, "PUT", "put_answers"),
    ("/career/shortlist", put_shortlist, "PUT", "put_shortlist"),
    ("/career/choice", put_choice, "PUT", "put_choice"),
    ("/career/spike", put_spike, "PUT", "put_spike"),
    ("/career/professions/suggest", suggest_professions, "POST", "suggest_professions"),
    ("/career/majors/fit", suggest_fit, "POST", "suggest_fit"),
    ("/career/spike/suggest", suggest_spike, "POST", "suggest_spike"),
):
    router.add_api_route(
        path,
        endpoint,
        methods=[method],
        operation_id=f"admission_career_{op}",
        response_model=CareerPlanOut,
    )
router.add_api_route(
    "/career/questions",
    list_questions,
    methods=["GET"],
    response_model=QuestionsOut,
    operation_id="admission_career_list_questions",
)
router.add_api_route(
    "/career/majors",
    list_majors,
    methods=["GET"],
    response_model=MajorsOut,
    operation_id="admission_career_list_majors",
)
router.add_api_route(
    "/career/admin/questions",
    admin_questions,
    methods=["GET"],
    response_model=QuestionsOut,
    operation_id="admission_career_admin_questions",
)
router.add_api_route(
    "/career/admin/questions",
    admin_create_question,
    methods=["POST"],
    status_code=201,
    response_model=QuestionOut,
    operation_id="admission_career_admin_create_question",
)
router.add_api_route(
    "/career/admin/questions/{question_id}",
    admin_put_question,
    methods=["PUT"],
    response_model=QuestionOut,
    operation_id="admission_career_admin_put_question",
)
router.add_api_route(
    "/career/admin/majors",
    admin_majors,
    methods=["GET"],
    response_model=MajorsOut,
    operation_id="admission_career_admin_majors",
)
router.add_api_route(
    "/career/admin/majors",
    admin_create_major,
    methods=["POST"],
    status_code=201,
    response_model=MajorOut,
    operation_id="admission_career_admin_create_major",
)
router.add_api_route(
    "/career/admin/majors/{major_id}",
    admin_put_major,
    methods=["PUT"],
    response_model=MajorOut,
    operation_id="admission_career_admin_put_major",
)
router.add_api_route(
    "/voice/transcriptions",
    transcribe,
    methods=["POST"],
    response_model=TranscriptOut,
    operation_id="admission_voice_transcribe",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"audio/*": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
router.add_api_route(
    "/voice/speech",
    speak,
    methods=["POST"],
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}}},
    operation_id="admission_voice_speech",
)
