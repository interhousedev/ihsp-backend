"""Documents, checklist, transcripts, officer and deadline routes."""

import datetime as dt
from typing import Annotated, Final, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import (
    AdmissionCtx,
    ContainerDep,
    ensure_applicant,
)
from app.modules.admission.application.deadlines import DeadlineInput, DeadlineItem
from app.modules.admission.application.documents import DocumentView
from app.modules.admission.application.transcripts import TranscriptView
from app.modules.admission.domain.checklist import UNSET, deep_link, is_urgent, quadrant
from app.modules.admission.domain.documents import (
    UPLOAD_MIME,
    AttachmentRecord,
    ChecklistItem,
    ChecklistStatus,
    Deadline,
    OfficerSettings,
    ReminderPrefs,
    Transcript,
    sniff_upload,
)
from app.modules.admission.domain.institution_brand import InstitutionBrand
from app.modules.admission.domain.workflow import DocumentKind
from app.modules.files.domain.errors import FileTooLargeError, TypeNotAllowedError

from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

_BRAND_FIELDS: Final = frozenset(
    {"institution_name", "logo_url", "logo_fit", "logo_zoom", "institution_website_url"}
)


class VersionOut(BaseModel):
    """One uploaded version of a document."""

    version: int
    file_id: UUID
    scan_status: str
    uploaded_at: dt.datetime | None


class AttachmentOut(BaseModel):
    """A document attached to a list entry."""

    id: UUID
    document_id: UUID
    document_version: int
    list_entry_id: UUID
    status: str

    @classmethod
    def of(cls, a: AttachmentRecord) -> "AttachmentOut":
        """Map the record."""
        return cls(
            id=a.id,
            document_id=a.document_id,
            document_version=a.document_version,
            list_entry_id=a.list_entry_id,
            status=a.status,
        )


class DocumentOut(BaseModel):
    """A document with its versions and attachments."""

    id: UUID
    student_id: UUID
    kind: str
    visibility: str
    current_version: int
    review_status: str
    reject_reason_code: str | None
    reject_note: str | None
    created_at: dt.datetime | None
    versions: list[VersionOut]
    attachments: list[AttachmentOut]
    can_download: bool

    @classmethod
    def of(cls, v: DocumentView) -> "DocumentOut":
        """Map the view."""
        d = v.doc
        return cls(
            id=d.id,
            student_id=d.student_id,
            kind=d.kind,
            visibility=d.visibility,
            current_version=d.current_version,
            review_status=d.review_status,
            reject_reason_code=d.reject_reason_code,
            reject_note=d.reject_note,
            created_at=d.created_at,
            versions=[
                VersionOut(
                    version=x.version,
                    file_id=x.file_id,
                    scan_status=x.scan_status,
                    uploaded_at=x.uploaded_at,
                )
                for x in v.versions
            ],
            attachments=[AttachmentOut.of(a) for a in v.attachments],
            can_download=v.can_download,
        )


class ReviewIn(BaseModel):
    """A review decision."""

    model_config = ConfigDict(extra="forbid")

    accept: bool
    reason_code: str | None = None
    note: str | None = None


class AttachIn(BaseModel):
    """The list entry to attach to."""

    model_config = ConfigDict(extra="forbid")

    list_entry_id: UUID


class DownloadOut(BaseModel):
    """A short-lived signed link."""

    url: str
    expires_at: dt.datetime


class ChecklistOut(BaseModel):
    """One checklist item."""

    id: UUID
    template_key: str
    title_key: str
    list_entry_id: UUID | None
    owner: str
    status: str
    due_utc: dt.datetime | None
    document_id: UUID | None
    source_url: str | None
    important: bool
    urgent_override: bool | None
    institution_name: str | None = None
    logo_url: str | None = None
    logo_fit: Literal["circle", "contain"] = "circle"
    logo_zoom: float = 1.0
    institution_website_url: str | None = None
    app_path: str | None = None
    urgent: bool = False
    quadrant: Literal["do", "schedule", "delegate", "drop"] = "drop"

    @classmethod
    def of(
        cls, c: ChecklistItem, brand: InstitutionBrand | None = None
    ) -> "ChecklistOut":
        """Map the item; the brand is set for per-university items."""
        derived = {*_BRAND_FIELDS, "app_path", "urgent", "quadrant"}
        data = {k: getattr(c, k) for k in cls.model_fields if k not in derived}
        now = dt.datetime.now(dt.UTC)
        return cls(
            **data,
            institution_name=brand.name if brand else None,
            logo_url=brand.logo_url if brand else None,
            logo_fit=brand.logo_fit if brand else "circle",
            logo_zoom=brand.logo_zoom if brand else 1.0,
            institution_website_url=brand.website_url if brand else None,
            app_path=deep_link(c.template_key),
            urgent=is_urgent(c, now),
            quadrant=quadrant(c, now),
        )


class ChecklistPatchIn(BaseModel):
    """Checklist item changes."""

    model_config = ConfigDict(extra="forbid")

    status: ChecklistStatus | None = None
    document_id: UUID | None = None
    important: bool | None = None
    urgent_override: bool | None = None
    source_url: str | None = Field(default=None, max_length=2000)


class TranscriptOut(BaseModel):
    """A transcript request; student and class only for officers."""

    id: UUID
    student_id: UUID | None
    student_name: str | None = None
    class_name: str | None = None
    destination_note: str
    status: str
    requested_at: dt.datetime | None
    ready_at: dt.datetime | None
    undo_until: dt.datetime | None
    pickup_location: str | None
    document_id: UUID | None
    lock_version: int

    @classmethod
    def of(cls, t: Transcript, *, officer: bool = False) -> "TranscriptOut":
        """Map a request; the officer view hides the student id."""
        return cls(
            id=t.id,
            student_id=None if officer else t.student_id,
            destination_note=t.destination_note,
            status=t.status,
            requested_at=t.requested_at,
            ready_at=t.ready_at,
            undo_until=t.undo_until,
            pickup_location=t.pickup_location_snapshot,
            document_id=None if officer else t.document_id,
            lock_version=t.lock_version,
        )

    @classmethod
    def of_view(cls, v: TranscriptView, *, officer: bool = False) -> "TranscriptOut":
        """Map a request with display names."""
        out = cls.of(v.request, officer=officer)
        out.student_name = v.student_name
        out.class_name = v.class_name
        return out


class TranscriptRequestIn(BaseModel):
    """Where the transcript is needed."""

    model_config = ConfigDict(extra="forbid")

    destination_note: str = ""


class TranscriptRequestOut(BaseModel):
    """The request and whether an open one was reused."""

    request: TranscriptOut
    reused: bool


class DoneIn(BaseModel):
    """Optional optimistic lock."""

    model_config = ConfigDict(extra="forbid")

    lock_version: int | None = None


class DoneOut(BaseModel):
    """Done outcome."""

    request: TranscriptOut
    already: bool


class OfficerSettingsOut(BaseModel):
    """The officer's pickup location per locale."""

    pickup_location: dict[str, str]

    @classmethod
    def of(cls, s: OfficerSettings) -> "OfficerSettingsOut":
        """Map the settings."""
        return cls(pickup_location=s.pickup_location)


class OfficerSettingsIn(BaseModel):
    """Pickup location per locale (uz, ru, en)."""

    model_config = ConfigDict(extra="forbid")

    pickup_location: dict[str, str]


class DeadlineOut(BaseModel):
    """A deadline version."""

    id: UUID
    institution_id: UUID
    institution_name: str = ""
    logo_url: str | None = None
    logo_fit: Literal["circle", "contain"] = "circle"
    logo_zoom: float = 1.0
    cycle: int
    round: str
    program_id: UUID | None
    precision: str
    source_text: str | None
    source_tz: str | None
    local_date: dt.date | None
    cutoff_time: dt.time | None
    instant_utc: dt.datetime | None
    binding: bool
    applies_to: str | None
    status: str
    version: int

    @classmethod
    def of(cls, d: Deadline, brand: InstitutionBrand | None = None) -> "DeadlineOut":
        """Map the deadline; the caller supplies the university brand."""
        brand = brand or InstitutionBrand("")
        keys = set(cls.model_fields) - _BRAND_FIELDS
        return cls(
            institution_name=brand.name,
            logo_url=brand.logo_url,
            logo_fit=brand.logo_fit,
            logo_zoom=brand.logo_zoom,
            **{k: getattr(d, k) for k in keys},
        )


class MilestoneOut(BaseModel):
    """A dated step of a list entry."""

    id: UUID
    list_entry_id: UUID
    kind: str
    due_utc: dt.datetime | None
    predicted: bool
    institution_id: UUID
    institution_name: str
    logo_url: str | None = None
    logo_fit: Literal["circle", "contain"] = "circle"
    logo_zoom: float = 1.0

    @classmethod
    def of(cls, i: DeadlineItem) -> "MilestoneOut":
        """Map the item."""
        m = i.milestone
        return cls(
            id=m.id,
            list_entry_id=m.list_entry_id,
            kind=m.kind,
            due_utc=m.due_utc,
            predicted=m.predicted,
            institution_id=i.institution_id,
            institution_name=i.brand.name,
            logo_url=i.brand.logo_url,
            logo_fit=i.brand.logo_fit,
            logo_zoom=i.brand.logo_zoom,
        )


class DeadlineIn(BaseModel):
    """Create a deadline."""

    model_config = ConfigDict(extra="forbid")

    institution_id: UUID
    cycle: int
    round: str
    program_id: UUID | None = None
    status: str | None = None
    precision: str | None = None
    source_text: str | None = None
    source_tz: str | None = None
    local_date: dt.date | None = None
    cutoff_time: dt.time | None = None
    instant_utc: dt.datetime | None = None
    binding: bool | None = None
    applies_to: str | None = None


class DeadlinePatchIn(BaseModel):
    """Edit a deadline (creates a new version)."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    precision: str | None = None
    source_text: str | None = None
    source_tz: str | None = None
    local_date: dt.date | None = None
    cutoff_time: dt.time | None = None
    instant_utc: dt.datetime | None = None
    binding: bool | None = None
    applies_to: str | None = None


class PrefsOut(BaseModel):
    """Reminder preferences."""

    offsets_days: list[int]
    channels: list[str]
    quiet_from: dt.time
    quiet_to: dt.time

    @classmethod
    def of(cls, p: ReminderPrefs) -> "PrefsOut":
        """Map the preferences."""
        return cls(
            offsets_days=list(p.offsets_days),
            channels=list(p.channels),
            quiet_from=p.quiet_from,
            quiet_to=p.quiet_to,
        )


class PrefsIn(PrefsOut):
    """Replacement preferences."""

    model_config = ConfigDict(extra="forbid")


async def _read(container: ContainerDep, ctx: AdmissionCtx, file: UploadFile) -> bytes:
    """Read an upload: at most the admin-set size, and only PDF, JPEG or PNG."""
    limit = await container.admission.documents.upload_limit(ctx.user_id)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise FileTooLargeError(params={"max_mb": round(limit / (1024 * 1024), 1)})
    if sniff_upload(data[:8]) is None:
        raise TypeNotAllowedError(params={"types": ", ".join(UPLOAD_MIME)})
    return data


# -- documents --------------------------------------------------------------


async def list_documents(
    container: ContainerDep, ctx: AdmissionCtx, student_id: UUID | None = None
) -> list[DocumentOut]:
    """List my documents (staff pass `student_id`)."""
    if student_id is None:
        ensure_applicant(ctx)
    views = await container.admission.documents.listing(ctx, student_id)
    return [DocumentOut.of(v) for v in views]


async def upload_document(
    container: ContainerDep,
    ctx: AdmissionCtx,
    kind: Annotated[DocumentKind, Form()],
    file: Annotated[UploadFile, File()],
    student_id: Annotated[UUID | None, Form()] = None,
) -> DocumentOut:
    """Upload a document as its first version."""
    data = await _read(container, ctx, file)
    svc = container.admission.documents
    doc = await svc.upload(
        ctx, kind, file.filename or "document", data, student_id=student_id
    )
    views = await svc.listing(ctx, doc.doc.student_id if student_id else None)
    return DocumentOut.of(next(v for v in views if v.doc.id == doc.doc.id))


async def upload_version(
    doc_id: UUID,
    container: ContainerDep,
    ctx: AdmissionCtx,
    file: Annotated[UploadFile, File()],
) -> DocumentOut:
    """Upload a new version; old attachments need re-confirmation."""
    data = await _read(container, ctx, file)
    svc = container.admission.documents
    doc = await svc.new_version(ctx, doc_id, file.filename or "document", data)
    views = await svc.listing(ctx, doc.doc.student_id)
    return DocumentOut.of(next(v for v in views if v.doc.id == doc.doc.id))


async def review_document(
    doc_id: UUID, body: ReviewIn, container: ContainerDep, ctx: AdmissionCtx
) -> DocumentOut:
    """Accept or reject a document."""
    svc = container.admission.documents
    doc = await svc.review(
        ctx, doc_id, accept=body.accept, reason_code=body.reason_code, note=body.note
    )
    views = await svc.listing(ctx, doc.doc.student_id)
    return DocumentOut.of(next(v for v in views if v.doc.id == doc.doc.id))


async def attach_document(
    doc_id: UUID, body: AttachIn, container: ContainerDep, ctx: AdmissionCtx
) -> AttachmentOut:
    """Attach the document to a list entry."""
    att = await container.admission.documents.attach(ctx, doc_id, body.list_entry_id)
    return AttachmentOut.of(att)


async def detach_document(
    doc_id: UUID, list_entry_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> None:
    """Detach the document from a list entry."""
    await container.admission.documents.detach(ctx, doc_id, list_entry_id)


async def download_document(
    doc_id: UUID,
    container: ContainerDep,
    ctx: AdmissionCtx,
    version: int | None = Query(default=None),
) -> DownloadOut:
    """Issue a signed link (5 minutes at most) after every check."""
    got = await container.admission.documents.download(ctx, doc_id, version)
    return DownloadOut(url=got.url, expires_at=got.expires_at)


async def staff_documents(
    container: ContainerDep, ctx: AdmissionCtx, review_status: str | None = None
) -> list[DocumentOut]:
    """Documents of the students in the caller's scope."""
    views = await container.admission.documents.staff_queue(ctx, review_status)
    return [DocumentOut.of(v) for v in views]


async def get_checklist(
    container: ContainerDep, ctx: AdmissionCtx, student_id: UUID | None = None
) -> list[ChecklistOut]:
    """The document checklist."""
    items = await container.admission.documents.checklist(ctx, student_id)
    return [ChecklistOut.of(i, brand) for i, brand in items]


async def patch_checklist(
    item_id: UUID, body: ChecklistPatchIn, container: ContainerDep, ctx: AdmissionCtx
) -> ChecklistOut:
    """Change a checklist item."""
    item, brand = await container.admission.documents.patch_checklist(
        ctx,
        item_id,
        status=body.status,
        document_id=body.document_id,
        important=body.important,
        urgent_override=(
            body.urgent_override
            if "urgent_override" in body.model_fields_set
            else UNSET
        ),
        source_url=body.source_url if "source_url" in body.model_fields_set else UNSET,
    )
    return ChecklistOut.of(item, brand)


# -- transcripts ------------------------------------------------------------


async def request_transcript(
    body: TranscriptRequestIn, container: ContainerDep, ctx: AdmissionCtx
) -> TranscriptRequestOut:
    """Ask the registrar for a transcript."""
    req, reused = await container.admission.transcripts.request(
        ctx, body.destination_note
    )
    return TranscriptRequestOut(request=TranscriptOut.of(req), reused=reused)


async def my_transcripts(
    container: ContainerDep, ctx: AdmissionCtx
) -> list[TranscriptOut]:
    """My transcript requests."""
    items = await container.admission.transcripts.mine(ctx)
    return [TranscriptOut.of(t) for t in items]


async def cancel_transcript(
    request_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> TranscriptOut:
    """Cancel a request."""
    return TranscriptOut.of(
        await container.admission.transcripts.cancel(ctx, request_id)
    )


async def upload_transcript_scan(
    request_id: UUID,
    container: ContainerDep,
    ctx: AdmissionCtx,
    file: Annotated[UploadFile, File()],
) -> DocumentOut:
    """Attach the scanned transcript."""
    data = await _read(container, ctx, file)
    view = await container.admission.transcripts.upload_scan(
        ctx, request_id, name=file.filename or "transcript", data=data
    )
    return DocumentOut.of(view)


async def officer_transcripts(
    container: ContainerDep,
    ctx: AdmissionCtx,
    status: Literal["requested", "ready", "cancelled"] = Query("requested"),
) -> list[TranscriptOut]:
    """Officer queue by status (name, class, note only); open by default."""
    items = await container.admission.transcripts.officer_queue(ctx, status)
    return [TranscriptOut.of_view(v, officer=True) for v in items]


async def officer_done(
    request_id: UUID, body: DoneIn, container: ContainerDep, ctx: AdmissionCtx
) -> DoneOut:
    """Mark ready; the student is notified after the undo window."""
    res = await container.admission.transcripts.done(
        ctx, request_id, lock_version=body.lock_version
    )
    return DoneOut(
        request=TranscriptOut.of(res.request, officer=True), already=res.already
    )


async def officer_undo(
    request_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> TranscriptOut:
    """Undo Done within the window."""
    t = await container.admission.transcripts.undo(ctx, request_id)
    return TranscriptOut.of(t, officer=True)


async def get_officer_settings(
    container: ContainerDep, ctx: AdmissionCtx
) -> OfficerSettingsOut:
    """The pickup location (of the officer or, from the admin page, an admin)."""
    return OfficerSettingsOut.of(
        await container.admission.transcripts.get_officer_settings(ctx)
    )


async def put_officer_settings(
    body: OfficerSettingsIn, container: ContainerDep, ctx: AdmissionCtx
) -> OfficerSettingsOut:
    """Set the pickup location per locale."""
    return OfficerSettingsOut.of(
        await container.admission.transcripts.set_pickup(ctx, body.pickup_location)
    )


async def staff_transcripts(
    container: ContainerDep, ctx: AdmissionCtx, status: str | None = None
) -> list[TranscriptOut]:
    """The oversee queue."""
    items = await container.admission.transcripts.overview(ctx, status)
    return [TranscriptOut.of_view(v) for v in items]


async def remind_transcript(
    request_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> TranscriptOut:
    """Remind officers (once per day)."""
    return TranscriptOut.of(
        await container.admission.transcripts.remind(ctx, request_id)
    )


# -- deadlines --------------------------------------------------------------


async def my_deadlines(
    container: ContainerDep, ctx: AdmissionCtx, student_id: UUID | None = None
) -> list[MilestoneOut]:
    """Deadlines of the list's universities."""
    if student_id is None:
        ensure_applicant(ctx)
    items = await container.admission.deadlines.mine(ctx, student_id)
    return [MilestoneOut.of(i) for i in items]


async def get_prefs(
    container: ContainerDep, ctx: AdmissionCtx, student_id: UUID | None = None
) -> PrefsOut:
    """Reminder preferences."""
    return PrefsOut.of(await container.admission.deadlines.get_prefs(ctx, student_id))


async def put_prefs(
    body: PrefsIn, container: ContainerDep, ctx: AdmissionCtx
) -> PrefsOut:
    """Replace reminder preferences."""
    return PrefsOut.of(
        await container.admission.deadlines.set_prefs(
            ctx,
            offsets_days=body.offsets_days,
            channels=body.channels,
            quiet_from=body.quiet_from,
            quiet_to=body.quiet_to,
        )
    )


async def staff_deadlines(
    container: ContainerDep,
    ctx: AdmissionCtx,
    institution_id: UUID | None = None,
    cycle: int | None = None,
) -> list[DeadlineOut]:
    """Live deadlines."""
    items = await container.admission.deadlines.listing(
        ctx, institution_id=institution_id, cycle=cycle
    )
    brands = await container.admission.deadlines.institution_brands(
        ctx, {d.institution_id for d in items}
    )
    return [DeadlineOut.of(d, brands.get(d.institution_id)) for d in items]


async def create_deadline(
    body: DeadlineIn, container: ContainerDep, ctx: AdmissionCtx
) -> DeadlineOut:
    """Add a deadline."""
    scope = {"institution_id", "cycle", "round", "program_id"}
    data = DeadlineInput(**body.model_dump(exclude=scope))
    d = await container.admission.deadlines.create(
        ctx,
        institution_id=body.institution_id,
        cycle=body.cycle,
        round=body.round,
        program_id=body.program_id,
        data=data,
    )
    return DeadlineOut.of(d)


async def edit_deadline(
    deadline_id: UUID,
    body: DeadlinePatchIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
) -> DeadlineOut:
    """Edit a deadline; students on the list are told."""
    patch = body.model_dump(exclude_unset=True)
    data = DeadlineInput.from_patch(patch)
    d = await container.admission.deadlines.edit(ctx, deadline_id, data)
    return DeadlineOut.of(d)


async def remove_deadline(
    deadline_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> None:
    """Retire a deadline."""
    await container.admission.deadlines.remove(ctx, deadline_id)


for _path, _fn, _method, _model, _op, _status in (
    (
        "/documents",
        list_documents,
        "GET",
        list[DocumentOut],
        "admission_list_documents",
        200,
    ),
    (
        "/documents",
        upload_document,
        "POST",
        DocumentOut,
        "admission_upload_document",
        201,
    ),
    (
        "/documents/{doc_id}/versions",
        upload_version,
        "POST",
        DocumentOut,
        "admission_upload_document_version",
        201,
    ),
    (
        "/documents/{doc_id}/review",
        review_document,
        "POST",
        DocumentOut,
        "admission_review_document",
        200,
    ),
    (
        "/documents/{doc_id}/attachments",
        attach_document,
        "POST",
        AttachmentOut,
        "admission_attach_document",
        201,
    ),
    (
        "/documents/{doc_id}/attachments/{list_entry_id}",
        detach_document,
        "DELETE",
        None,
        "admission_detach_document",
        204,
    ),
    (
        "/documents/{doc_id}/download",
        download_document,
        "POST",
        DownloadOut,
        "admission_download_document",
        200,
    ),
    (
        "/staff/documents",
        staff_documents,
        "GET",
        list[DocumentOut],
        "admission_staff_documents",
        200,
    ),
    (
        "/checklist",
        get_checklist,
        "GET",
        list[ChecklistOut],
        "admission_get_checklist",
        200,
    ),
    (
        "/checklist/{item_id}",
        patch_checklist,
        "PATCH",
        ChecklistOut,
        "admission_patch_checklist",
        200,
    ),
    (
        "/transcripts",
        request_transcript,
        "POST",
        TranscriptRequestOut,
        "admission_request_transcript",
        201,
    ),
    (
        "/transcripts",
        my_transcripts,
        "GET",
        list[TranscriptOut],
        "admission_my_transcripts",
        200,
    ),
    (
        "/transcripts/{request_id}/cancel",
        cancel_transcript,
        "POST",
        TranscriptOut,
        "admission_cancel_transcript",
        200,
    ),
    (
        "/transcripts/{request_id}/scan",
        upload_transcript_scan,
        "POST",
        DocumentOut,
        "admission_upload_transcript_scan",
        201,
    ),
    (
        "/officer/transcripts",
        officer_transcripts,
        "GET",
        list[TranscriptOut],
        "admission_officer_transcripts",
        200,
    ),
    (
        "/officer/transcripts/{request_id}/done",
        officer_done,
        "POST",
        DoneOut,
        "admission_officer_transcript_done",
        200,
    ),
    (
        "/officer/transcripts/{request_id}/undo",
        officer_undo,
        "POST",
        TranscriptOut,
        "admission_officer_transcript_undo",
        200,
    ),
    (
        "/officer/settings",
        get_officer_settings,
        "GET",
        OfficerSettingsOut,
        "admission_get_officer_settings",
        200,
    ),
    (
        "/officer/settings",
        put_officer_settings,
        "PUT",
        OfficerSettingsOut,
        "admission_put_officer_settings",
        200,
    ),
    (
        "/staff/transcripts",
        staff_transcripts,
        "GET",
        list[TranscriptOut],
        "admission_staff_transcripts",
        200,
    ),
    (
        "/staff/transcripts/{request_id}/remind",
        remind_transcript,
        "POST",
        TranscriptOut,
        "admission_remind_transcript",
        200,
    ),
    (
        "/deadlines",
        my_deadlines,
        "GET",
        list[MilestoneOut],
        "admission_my_deadlines",
        200,
    ),
    (
        "/reminder-prefs",
        get_prefs,
        "GET",
        PrefsOut,
        "admission_get_reminder_prefs",
        200,
    ),
    (
        "/reminder-prefs",
        put_prefs,
        "PUT",
        PrefsOut,
        "admission_put_reminder_prefs",
        200,
    ),
    (
        "/staff/deadlines",
        staff_deadlines,
        "GET",
        list[DeadlineOut],
        "admission_staff_deadlines",
        200,
    ),
    (
        "/staff/deadlines",
        create_deadline,
        "POST",
        DeadlineOut,
        "admission_create_deadline",
        201,
    ),
    (
        "/staff/deadlines/{deadline_id}",
        edit_deadline,
        "PATCH",
        DeadlineOut,
        "admission_edit_deadline",
        200,
    ),
    (
        "/staff/deadlines/{deadline_id}",
        remove_deadline,
        "DELETE",
        None,
        "admission_remove_deadline",
        204,
    ),
):
    router.add_api_route(
        _path,
        _fn,
        methods=[_method],
        response_model=_model,
        operation_id=_op,
        status_code=_status,
    )
