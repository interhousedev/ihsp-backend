"""Prompt studio routes: counselors edit, test and activate reviewer prompts."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AnyContext, ContainerDep
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.prompt_studio import (
    SampleResult,
    SavedVersion,
    StudioReport,
)
from app.modules.admission.domain.prompt_studio import (
    MAX_PROMPT_CONTEXT_CHARS,
    MAX_SAMPLE_CHARS,
    MAX_SAMPLES,
    PromptIssue,
    PromptVersionInfo,
    SampleInput,
    SlotState,
)

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission/staff/prompt-studio", tags=["admission"])

Lang = Annotated[str | None, Header(alias="Accept-Language")]
Locale = Literal["", "uz", "ru", "en"]
TextField = Annotated[str, Field(min_length=1, max_length=50_000)]

_ERRORS: dict[int | str, dict[str, Any]] = {
    403: {"description": "The caller may not edit the essay prompts"},
    404: {"description": "Unknown slot, version, exemplar or university"},
    422: {"description": "The draft or the samples are invalid"},
}
_TEST_ERRORS: dict[int | str, dict[str, Any]] = {
    **_ERRORS,
    429: {"description": "Daily test-run limit reached"},
}


class IssueOut(BaseModel):
    """A finding of the draft validation."""

    severity: Literal["error", "warning"]
    code: str
    detail: str

    @classmethod
    def of(cls, i: PromptIssue) -> "IssueOut":
        """Build from a domain issue."""
        return cls(severity=i.severity, code=i.code, detail=i.detail)


class VersionOut(BaseModel):
    """One stored prompt version."""

    version: int
    locale: str
    text: str
    hash: str
    active: bool
    note: str
    created_at: datetime

    @classmethod
    def of(cls, v: PromptVersionInfo) -> "VersionOut":
        """Build from a domain version."""
        return cls(**{f: getattr(v, f) for f in cls.model_fields})


class SlotOut(BaseModel):
    """A prompt slot with its active text and history."""

    task: str
    name: str
    summary: str
    template: bool
    fields: list[str]
    builtin: str
    active_text: str
    active_version: int
    active_hash: str
    versions: list[VersionOut]

    @classmethod
    def of(cls, s: SlotState) -> "SlotOut":
        """Build from a slot state."""
        return cls(
            task=s.slot.task,
            name=s.slot.name,
            summary=s.slot.summary,
            template=s.slot.template,
            fields=list(s.slot.fields),
            builtin=s.slot.builtin,
            active_text=s.active.text,
            active_version=s.active.version,
            active_hash=s.active.hash,
            versions=[VersionOut.of(v) for v in s.versions],
        )


class SlotListOut(BaseModel):
    """The editable slots."""

    items: list[SlotOut]


class SavedOut(BaseModel):
    """A stored version with the non-blocking findings."""

    version: VersionOut
    warnings: list[IssueOut]


class SaveIn(BaseModel):
    """A new prompt version."""

    text: TextField
    locale: Locale = ""
    note: str = Field("", max_length=200)


class SampleIn(BaseModel):
    """A pasted essay or a library exemplar; never a student's essay."""

    text: str | None = Field(None, max_length=MAX_SAMPLE_CHARS)
    exemplar_id: UUID | None = None
    prompt_text: str = Field("", max_length=MAX_PROMPT_CONTEXT_CHARS)
    kind: str = Field("personal_statement", max_length=40)


class StudioTestIn(BaseModel):
    """A draft to run against the active prompt."""

    text: TextField
    samples: list[SampleIn] = Field(min_length=1, max_length=MAX_SAMPLES)
    institution_id: UUID | None = None
    locale: Literal["uz", "ru", "en"] | None = None


class RunOut(BaseModel):
    """One model run."""

    model: str
    output: dict[str, Any]


class DeltaOut(BaseModel):
    """How the draft differs from the active prompt."""

    score_delta: int | None
    band_before: str | None
    band_after: str | None
    band_changed: bool


class SampleResultOut(BaseModel):
    """Both runs on one sample."""

    label: str
    exemplar_id: UUID | None
    active: RunOut
    draft: RunOut
    delta: DeltaOut

    @classmethod
    def of(cls, r: SampleResult) -> "SampleResultOut":
        """Build from a domain result."""
        return cls(
            label=r.label,
            exemplar_id=r.exemplar_id,
            active=RunOut(model=r.active.model, output=r.active.output),
            draft=RunOut(model=r.draft.model, output=r.draft.output),
            delta=DeltaOut(
                score_delta=r.delta.score_delta,
                band_before=r.delta.band_before,
                band_after=r.delta.band_after,
                band_changed=r.delta.band_changed,
            ),
        )


class ReportOut(BaseModel):
    """The comparison on every sample."""

    warnings: list[IssueOut]
    results: list[SampleResultOut]

    @classmethod
    def of(cls, r: StudioReport) -> "ReportOut":
        """Build from a domain report."""
        return cls(
            warnings=[IssueOut.of(i) for i in r.warnings],
            results=[SampleResultOut.of(x) for x in r.results],
        )


async def list_slots(container: ContainerDep, ctx: AnyContext) -> SlotListOut:
    """The four editable reviewer prompts with their active text."""
    rows = await container.admission.prompt_studio.slots(ctx)
    return SlotListOut(items=[SlotOut.of(s) for s in rows])


async def get_slot(
    task: str,
    name: str,
    container: ContainerDep,
    ctx: AnyContext,
    locale: Annotated[Locale, Query()] = "",
) -> SlotOut:
    """One slot with the text in force for a locale and its versions."""
    state = await container.admission.prompt_studio.slot(ctx, task, name, locale)
    return SlotOut.of(state)


async def save_version(
    task: str, name: str, body: SaveIn, container: ContainerDep, ctx: AnyContext
) -> SavedOut:
    """Store a validated draft as the new active version."""
    saved: SavedVersion = await container.admission.prompt_studio.save(
        ctx, task, name, text=body.text, locale=body.locale, note=body.note
    )
    return SavedOut(
        version=VersionOut.of(saved.version),
        warnings=[IssueOut.of(i) for i in saved.warnings],
    )


async def activate_version(
    task: str, name: str, version: int, container: ContainerDep, ctx: AnyContext
) -> VersionOut:
    """Make a stored version the active one."""
    done = await container.admission.prompt_studio.activate(ctx, task, name, version)
    return VersionOut.of(done)


async def revert_slot(
    task: str,
    name: str,
    container: ContainerDep,
    ctx: AnyContext,
    locale: Annotated[Locale, Query()] = "",
) -> None:
    """Drop the override so the built-in text applies again."""
    await container.admission.prompt_studio.revert(ctx, task, name, locale)


async def test_slot(
    task: str,
    name: str,
    body: StudioTestIn,
    container: ContainerDep,
    ctx: AnyContext,
    lang: Lang = None,
) -> ReportOut:
    """Run the draft and the active prompt on pasted samples and compare."""
    report = await container.admission.prompt_studio.test(
        ctx,
        task,
        name,
        text=body.text,
        samples=[
            SampleInput(s.text, s.exemplar_id, s.prompt_text, s.kind)
            for s in body.samples
        ],
        locale=body.locale or _locale(lang),
        institution_id=body.institution_id,
    )
    return ReportOut.of(report)


def _route(
    path: str,
    endpoint: Any,
    method: str,
    op: str,
    errors: dict[int | str, dict[str, Any]],
    **kw: Any,
) -> None:
    router.add_api_route(
        path,
        endpoint,
        methods=[method],
        operation_id=f"admission_{op}",
        responses=errors,
        **kw,
    )


_route(
    "/slots",
    list_slots,
    "GET",
    "prompt_studio_slots",
    _ERRORS,
    response_model=SlotListOut,
)
_route(
    "/slots/{task}/{name}",
    get_slot,
    "GET",
    "prompt_studio_slot",
    _ERRORS,
    response_model=SlotOut,
)
_route(
    "/slots/{task}/{name}",
    save_version,
    "PUT",
    "prompt_studio_save",
    _ERRORS,
    response_model=SavedOut,
)
_route(
    "/slots/{task}/{name}/versions/{version}/activate",
    activate_version,
    "POST",
    "prompt_studio_activate",
    _ERRORS,
    response_model=VersionOut,
)
_route(
    "/slots/{task}/{name}",
    revert_slot,
    "DELETE",
    "prompt_studio_revert",
    _ERRORS,
    status_code=204,
)
_route(
    "/slots/{task}/{name}/test",
    test_slot,
    "POST",
    "prompt_studio_test",
    _TEST_ERRORS,
    response_model=ReportOut,
)
