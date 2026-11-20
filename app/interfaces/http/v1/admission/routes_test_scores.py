"""Tests & certificates routes (`/v1/admission/test-scores*`)."""

import datetime as dt
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, AnyContext, ContainerDep
from app.modules.admission.application.score_certificates import ExamCertificate
from app.modules.admission.application.test_scores import ScoreOverview
from app.modules.admission.domain.test_scores import (
    LABEL_MAX,
    LEVEL_MAX,
    MAX_SECTIONS,
    NOTE_MAX,
    URL_MAX,
    ScoreEntry,
    ScoreEntryDraft,
    ScoreSummary,
    ScoreTest,
    SectionDef,
    to_json,
)

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

StatusT = Literal["planned", "registered", "taken", "score_received"]
TotalModeT = Literal["sum", "mean_int", "mean_half", "manual", "none"]
ScoreValue = int | float | str


class SectionDefIO(BaseModel):
    """A scored part of a test: a range and a step, or a list of choices."""

    key: str = Field(min_length=2, max_length=40)
    names: dict[str, str]
    min: float
    max: float
    step: float = Field(gt=0)
    choices: list[str] = Field(default_factory=list, max_length=30)

    @classmethod
    def of(cls, s: SectionDef) -> "SectionDefIO":
        """Map the section."""
        return cls(
            key=s.key,
            names=s.names,
            min=float(s.min),
            max=float(s.max),
            step=float(s.step),
            choices=list(s.choices),
        )

    def to_domain(self) -> SectionDef:
        """Build the domain section."""
        return SectionDef(
            key=self.key,
            names=self.names,
            min=Decimal(str(self.min)),
            max=Decimal(str(self.max)),
            step=Decimal(str(self.step)),
            choices=tuple(self.choices),
        )


class ScoreTestIn(BaseModel):
    """A test definition (administrators)."""

    key: str = Field(min_length=2, max_length=40)
    names: dict[str, str]
    sections: list[SectionDefIO] = Field(max_length=MAX_SECTIONS)
    total: SectionDefIO | None = None
    total_mode: TotalModeT
    superscore: bool = False
    needs_label: bool = False
    needs_level: bool = False
    position: int = Field(default=0, ge=0, le=1000)
    active: bool = True


class ScoreTestOut(BaseModel):
    """A catalog test."""

    id: UUID
    key: str
    names: dict[str, str]
    sections: list[SectionDefIO]
    total: SectionDefIO | None
    total_mode: str
    superscore: bool
    needs_label: bool
    needs_level: bool
    position: int
    active: bool

    @classmethod
    def of(cls, t: ScoreTest) -> "ScoreTestOut":
        """Map the test."""
        return cls(
            id=t.id,
            key=t.key,
            names=t.names,
            sections=[SectionDefIO.of(s) for s in t.sections],
            total=SectionDefIO.of(t.total) if t.total else None,
            total_mode=t.total_mode,
            superscore=t.superscore,
            needs_label=t.needs_label,
            needs_level=t.needs_level,
            position=t.position,
            active=t.active,
        )


class ScoreCatalogOut(BaseModel):
    """The tests students can record."""

    items: list[ScoreTestOut]
    can_edit: bool


class ScoreEntryIn(BaseModel):
    """An entry; unknown or out-of-range scores answer 422."""

    test_id: UUID
    status: StatusT
    test_date: dt.date | None = None
    registration_deadline: dt.date | None = None
    label: str | None = Field(default=None, max_length=LABEL_MAX)
    level: str | None = Field(default=None, max_length=LEVEL_MAX)
    sections: dict[str, ScoreValue] = Field(default_factory=dict)
    total: ScoreValue | None = None
    certificate_document_id: UUID | None = None
    verification_url: str | None = Field(default=None, max_length=URL_MAX)
    send_note: str | None = Field(default=None, max_length=NOTE_MAX)
    is_official: bool = False

    def to_domain(self) -> ScoreEntryDraft:
        """Build the draft."""
        return ScoreEntryDraft(
            test_id=self.test_id,
            status=self.status,
            test_date=self.test_date,
            registration_deadline=self.registration_deadline,
            label=self.label,
            level=self.level,
            sections=self.sections,
            total=self.total,
            certificate_document_id=self.certificate_document_id,
            verification_url=self.verification_url,
            send_note=self.send_note,
            is_official=self.is_official,
        )


class ScoreEntryOut(BaseModel):
    """A recorded sitting or certificate."""

    id: UUID
    test_id: UUID
    status: str
    test_date: dt.date | None
    registration_deadline: dt.date | None
    label: str | None
    level: str | None
    sections: dict[str, ScoreValue]
    total: ScoreValue | None
    certificate_document_id: UUID | None
    verification_url: str | None
    send_note: str | None
    is_official: bool
    verified_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime
    source: Literal["manual", "certificate"]
    """`certificate`: from the student's platform certificates, read-only here."""

    @classmethod
    def of(cls, e: ScoreEntry) -> "ScoreEntryOut":
        """Map the entry."""
        sections: dict[str, Any] = {k: to_json(v) for k, v in e.sections.items()}
        return cls(
            id=e.id,
            test_id=e.test_id,
            status=e.status,
            test_date=e.test_date,
            registration_deadline=e.registration_deadline,
            label=e.label,
            level=e.level,
            sections=sections,
            total=to_json(e.total),
            certificate_document_id=e.certificate_document_id,
            verification_url=e.verification_url,
            send_note=e.send_note,
            is_official=e.is_official,
            verified_at=e.verified_at,
            created_at=e.created_at,
            updated_at=e.updated_at,
            source=e.source,
        )


class ExamCertificateOut(BaseModel):
    """A standard certificate of the platform that no catalog test matches."""

    entry_id: UUID
    type_code: str
    name: dict[str, str]
    issued_at: dt.date | None
    expires_at: dt.date | None
    values: dict[str, Any]

    @classmethod
    def of(cls, c: ExamCertificate) -> "ExamCertificateOut":
        """Map the exam."""
        return cls(
            entry_id=c.entry_id,
            type_code=c.type_code,
            name=c.names,
            issued_at=c.issued_at,
            expires_at=c.expires_at,
            values=c.values,
        )


class ScoreSummaryOut(BaseModel):
    """Best result and superscore of one test."""

    test_id: UUID
    best_entry_id: UUID | None
    best_total: ScoreValue | None
    superscore_sections: dict[str, ScoreValue] | None
    superscore_total: ScoreValue | None

    @classmethod
    def of(cls, s: ScoreSummary) -> "ScoreSummaryOut":
        """Map the summary."""
        sup = (
            {k: to_json(v) for k, v in s.superscore_sections.items()}
            if s.superscore_sections is not None
            else None
        )
        return cls(
            test_id=s.test_id,
            best_entry_id=s.best_entry_id,
            best_total=to_json(s.best_total),
            superscore_sections=sup,
            superscore_total=to_json(s.superscore_total),
        )


class ScoreOverviewOut(BaseModel):
    """A student's entries with per-test summaries."""

    entries: list[ScoreEntryOut]
    summaries: list[ScoreSummaryOut]
    is_owner: bool
    can_verify: bool
    exams: list[ExamCertificateOut]

    @classmethod
    def of(cls, o: ScoreOverview) -> "ScoreOverviewOut":
        """Map the overview."""
        return cls(
            entries=[ScoreEntryOut.of(e) for e in o.entries],
            summaries=[ScoreSummaryOut.of(s) for s in o.summaries],
            is_owner=o.is_owner,
            can_verify=o.can_verify,
            exams=[ExamCertificateOut.of(c) for c in o.exams],
        )


class ScoreVerifyIn(BaseModel):
    """Mark an entry verified or not."""

    verified: bool


def _test_of(body: ScoreTestIn) -> ScoreTest:
    return ScoreTest(
        id=UUID(int=0),
        key=body.key,
        names=body.names,
        sections=tuple(s.to_domain() for s in body.sections),
        total=body.total.to_domain() if body.total else None,
        total_mode=body.total_mode,
        superscore=body.superscore,
        needs_label=body.needs_label,
        needs_level=body.needs_level,
        position=body.position,
        active=body.active,
    )


async def get_catalog(container: ContainerDep, ctx: AnyContext) -> ScoreCatalogOut:
    """Test definitions (administrators also see inactive ones)."""
    svc = container.admission.test_scores
    items = await svc.catalog(ctx)
    return ScoreCatalogOut(
        items=[ScoreTestOut.of(t) for t in items], can_edit=svc.is_admin(ctx)
    )


async def create_test(
    body: ScoreTestIn, container: ContainerDep, ctx: AnyContext
) -> ScoreTestOut:
    """Add a test definition (administrators)."""
    saved = await container.admission.test_scores.save_test(ctx, None, _test_of(body))
    return ScoreTestOut.of(saved)


async def update_test(
    test_id: UUID, body: ScoreTestIn, container: ContainerDep, ctx: AnyContext
) -> ScoreTestOut:
    """Replace a test definition (administrators)."""
    saved = await container.admission.test_scores.save_test(
        ctx, test_id, _test_of(body)
    )
    return ScoreTestOut.of(saved)


async def delete_test(
    test_id: UUID, container: ContainerDep, ctx: AnyContext
) -> Response:
    """Delete an unused test definition (administrators)."""
    await container.admission.test_scores.delete_test(ctx, test_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def my_scores(container: ContainerDep, ctx: AdmissionCtx) -> ScoreOverviewOut:
    """My entries and the best result and superscore per test."""
    return ScoreOverviewOut.of(await container.admission.test_scores.overview(ctx))


async def student_scores(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ScoreOverviewOut:
    """A student's entries (staff with access; audited)."""
    return ScoreOverviewOut.of(
        await container.admission.test_scores.overview(ctx, student_id)
    )


async def create_entry(
    body: ScoreEntryIn, container: ContainerDep, ctx: AdmissionCtx
) -> ScoreEntryOut:
    """Add an entry (at most 100)."""
    saved = await container.admission.test_scores.create(ctx, body.to_domain())
    return ScoreEntryOut.of(saved)


async def update_entry(
    entry_id: UUID, body: ScoreEntryIn, container: ContainerDep, ctx: AdmissionCtx
) -> ScoreEntryOut:
    """Replace my entry; this clears its verification."""
    saved = await container.admission.test_scores.update(
        ctx, entry_id, body.to_domain()
    )
    return ScoreEntryOut.of(saved)


async def delete_entry(
    entry_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Remove my entry."""
    await container.admission.test_scores.delete(ctx, entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def verify_entry(
    entry_id: UUID, body: ScoreVerifyIn, container: ContainerDep, ctx: AdmissionCtx
) -> ScoreEntryOut:
    """Mark a received result verified (staff with document review)."""
    saved = await container.admission.test_scores.verify(ctx, entry_id, body.verified)
    return ScoreEntryOut.of(saved)


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_CREATED = {"status_code": status.HTTP_201_CREATED}
_GONE = {"status_code": status.HTTP_204_NO_CONTENT}

_route(
    "/test-scores/catalog",
    get_catalog,
    "GET",
    "test_scores_catalog",
    response_model=ScoreCatalogOut,
)
_route(
    "/test-scores/catalog",
    create_test,
    "POST",
    "test_scores_catalog_create",
    response_model=ScoreTestOut,
    **_CREATED,
)
_route(
    "/test-scores/catalog/{test_id}",
    update_test,
    "PUT",
    "test_scores_catalog_update",
    response_model=ScoreTestOut,
)
_route(
    "/test-scores/catalog/{test_id}",
    delete_test,
    "DELETE",
    "test_scores_catalog_delete",
    **_GONE,
)
_route(
    "/test-scores",
    my_scores,
    "GET",
    "test_scores_list",
    response_model=ScoreOverviewOut,
)
_route(
    "/students/{student_id}/test-scores",
    student_scores,
    "GET",
    "test_scores_of_student",
    response_model=ScoreOverviewOut,
)
_route(
    "/test-scores",
    create_entry,
    "POST",
    "test_scores_create",
    response_model=ScoreEntryOut,
    **_CREATED,
)
_route(
    "/test-scores/{entry_id}",
    update_entry,
    "PUT",
    "test_scores_update",
    response_model=ScoreEntryOut,
)
_route("/test-scores/{entry_id}", delete_entry, "DELETE", "test_scores_delete", **_GONE)
_route(
    "/test-scores/{entry_id}/verify",
    verify_entry,
    "POST",
    "test_scores_verify",
    response_model=ScoreEntryOut,
)
