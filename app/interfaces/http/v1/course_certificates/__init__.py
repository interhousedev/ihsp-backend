"""Course certificate routes: staff design, learner status, public verification."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_client_ip, get_container
from app.modules.certificates.application.course_certificates import (
    CourseCertificates,
)
from app.modules.certificates.domain.course.rules import CertificateSettings, Tier
from app.modules.certificates.domain.course.values import (
    CertificateTemplate,
    CoursePartner,
    IssuedCertificate,
)
from app.modules.certificates.domain.errors import CourseCertificateNotFoundError
from app.modules.certificates.infrastructure import course_render
from app.shared.actor import Actor

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from pydantic import BaseModel, Field

ContainerDep = Annotated[Container, Depends(get_container)]
AnyActor = Annotated[Actor, Depends(get_actor)]
P = "/v1/certificates/courses"
IMAGE_CACHE = {"Cache-Control": "public, max-age=300"}

# Public routes are anonymous, so they are limited per client address.
PUBLIC_LIMIT = 60
PUBLIC_WINDOW_SECONDS = 60


def public_limit_key(ip: str | None, request: Request) -> str:
    """Key per client address; without one, per ASGI connection, never shared.

    The address is missing only when the server has no TCP peer (a Unix socket
    without a trusted proxy header). Keying such callers by their own receive
    channel means one of them can no longer exhaust a bucket shared by all.
    """
    if ip:
        return f"certificates:public:{ip}"
    return f"certificates:public:conn:{id(request.receive)}"


async def limit_public(
    request: Request,
    container: ContainerDep,
    ip: Annotated[str | None, Depends(get_client_ip)],
) -> None:
    """Count one public request per client; over the limit answers 429."""
    await container.rate_limiter.hit(
        public_limit_key(ip, request),
        limit=PUBLIC_LIMIT,
        window_seconds=PUBLIC_WINDOW_SECONDS,
    )


PUBLIC = [Depends(limit_public)]


def svc(container: Container) -> CourseCertificates:
    """Return the service."""
    return container.course_certificates


# - - - Schemas - - -


class Labels(BaseModel):
    """A text in every locale."""

    en: str = Field(max_length=60)
    ru: str = Field(max_length=60)
    uz: str = Field(max_length=60)


class TierBody(BaseModel):
    """A certificate tier, ordered low to high."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    label: Labels
    min_pct: int | None = Field(default=None, ge=0, le=100)
    require_optional: bool = False
    color: str = Field(default="#1f2937", pattern=r"^#[0-9a-fA-F]{6}$")


class SettingsBody(BaseModel):
    """Certificate settings of a course."""

    enabled: bool
    passing_pct: int = Field(ge=0, le=100)
    optional_section_ids: list[str] = Field(default_factory=list, max_length=200)
    tiers: list[TierBody] = Field(min_length=1, max_length=8)
    template_id: UUID | None = None
    partner_ids: list[UUID] = Field(default_factory=list, max_length=10)


def _tier(t: Tier) -> TierBody:
    return TierBody(
        key=t.key,
        label=Labels(**t.label),
        min_pct=t.min_pct,
        require_optional=t.require_optional,
        color=t.color,
    )


def _settings(s: CertificateSettings) -> SettingsBody:
    return SettingsBody(
        enabled=s.enabled,
        passing_pct=s.passing_pct,
        optional_section_ids=list(s.optional_section_ids),
        tiers=[_tier(t) for t in s.tiers],
        template_id=s.template_id,
        partner_ids=list(s.partner_ids),
    )


FieldKey = Literal[
    "name", "course", "tier", "date", "partner", "code", "qr", "custom_text"
]
FontKey = Literal["montserrat", "oswald", "lora", "eb_garamond", "cormorant"]


class TemplateField(BaseModel):
    """A placed field; positions and sizes are fractions of the page."""

    key: FieldKey
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(ge=0.01, le=1)
    h: float = Field(ge=0.01, le=1)
    font: FontKey = "montserrat"
    size: float = Field(default=0.05, ge=0.005, le=0.5)
    weight: int = Field(default=400, ge=100, le=900)
    color: str = Field(default="#111111", pattern=r"^#[0-9a-fA-F]{6}$")
    align: Literal["left", "center", "right"] = "center"
    text: str | None = Field(default=None, max_length=200)


class QrStyle(BaseModel):
    """QR colours, module style and the partner logo in the middle."""

    fg: str = Field(default="#000000", pattern=r"^#[0-9a-fA-F]{6}$")
    bg: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    style: Literal["square", "rounded", "dots"] = "square"
    logo: bool = False


class TemplateResponse(BaseModel):
    """A certificate design."""

    id: UUID
    name: str
    background_url: str | None
    width_px: int
    height_px: int
    fields: list[TemplateField]
    qr: QrStyle


class TemplateList(BaseModel):
    """Templates of a course."""

    items: list[TemplateResponse]


class TemplateCreate(BaseModel):
    """A new template."""

    name: str = Field(min_length=1, max_length=120)


class TemplateUpdate(BaseModel):
    """A template layout."""

    name: str = Field(min_length=1, max_length=120)
    fields: list[TemplateField] = Field(max_length=24)
    qr: QrStyle


def _template(row: CertificateTemplate) -> TemplateResponse:
    background = (
        f"/v1/certificates/templates/{row.id}/background.png?v={row.background_file_id}"
        if row.background_file_id
        else None
    )
    return TemplateResponse(
        id=row.id,
        name=row.name,
        background_url=background,
        width_px=row.width_px,
        height_px=row.height_px,
        fields=[TemplateField(**f) for f in row.fields],
        qr=QrStyle(**row.qr),
    )


class PartnerBody(BaseModel):
    """A partner of a course."""

    name: str = Field(min_length=1, max_length=160)
    url: str | None = Field(default=None, max_length=500)
    co_issued: bool = True


class PartnerResponse(BaseModel):
    """A partner with its logo link."""

    id: UUID
    name: str
    url: str | None
    logo_url: str | None
    co_issued: bool


class PartnerList(BaseModel):
    """Partners of a course."""

    items: list[PartnerResponse]


def _logo_url(partner_id: UUID | str, file_id: object) -> str | None:
    if not file_id:
        return None
    return f"/v1/certificates/partners/{partner_id}/logo.png?v={file_id}"


def _partner(row: CoursePartner) -> PartnerResponse:
    return PartnerResponse(
        id=row.id,
        name=row.name,
        url=row.url,
        logo_url=_logo_url(row.id, row.logo_file_id),
        co_issued=row.co_issued,
    )


class StudentRef(BaseModel):
    """The holder of a certificate."""

    id: UUID
    name: str


class IssuedItem(BaseModel):
    """An issued certificate in the staff list."""

    id: UUID
    student: StudentRef
    tier: str
    issued_at: datetime
    code: str
    revoked: bool


class IssuedList(BaseModel):
    """Certificates of a course."""

    items: list[IssuedItem]


class IssueResult(BaseModel):
    """How many learners hold a valid certificate."""

    issued: int


class RevokeBody(BaseModel):
    """Why a certificate is revoked."""

    reason: str = Field(min_length=1, max_length=500)


class MyCertificate(BaseModel):
    """The caller's certificate."""

    id: UUID
    code: str
    tier: Labels
    issued_at: datetime
    verify_url: str
    pdf_url: str
    revoked: bool


class MineResponse(BaseModel):
    """The caller's standing in the course."""

    eligible: bool
    progress_pct: int
    passing_pct: int
    next_tier: TierBody | None
    certificate: MyCertificate | None
    enabled: bool
    score_pct: int
    required_steps_left: int


class PublicPartner(BaseModel):
    """A partner as shown publicly."""

    name: str
    url: str | None = None
    logo_url: str | None


class VerifyResponse(BaseModel):
    """What the public verification page shows (minimal personal data)."""

    status: Literal["valid", "revoked"]
    holder_name: str
    course_title: str
    tier_label: Labels
    partner: PublicPartner | None
    issued_at: datetime
    qr_svg_url: str


class PublicCourseInfo(BaseModel):
    """Certificate facts for the course landing page."""

    enabled: bool
    passing_pct: int
    partners: list[PublicPartner]
    tiers: list[Labels]
    sample_url: str | None


# - - - Routes - - -

router = APIRouter(tags=["course-certificates"])


@router.get(
    P + "/{course_id}/settings", operation_id="course_certificates_get_settings"
)
async def get_settings(
    course_id: UUID, c: ContainerDep, actor: AnyActor
) -> SettingsBody:
    """Return the certificate settings of a course (course writers)."""
    return _settings(await svc(c).get_settings(actor.user_id, course_id))


@router.put(
    P + "/{course_id}/settings", operation_id="course_certificates_put_settings"
)
async def put_settings(
    course_id: UUID, body: SettingsBody, c: ContainerDep, actor: AnyActor
) -> SettingsBody:
    """Store the certificate settings of a course."""
    value = await svc(c).put_settings(
        actor.user_id, course_id, body.model_dump(mode="json")
    )
    return _settings(value)


@router.get(
    P + "/{course_id}/templates", operation_id="course_certificates_list_templates"
)
async def list_templates(
    course_id: UUID, c: ContainerDep, actor: AnyActor
) -> TemplateList:
    """Return the templates of a course."""
    rows = await svc(c).list_templates(actor.user_id, course_id)
    return TemplateList(items=[_template(r) for r in rows])


@router.post(
    P + "/{course_id}/templates", operation_id="course_certificates_create_template"
)
async def create_template(
    course_id: UUID, body: TemplateCreate, c: ContainerDep, actor: AnyActor
) -> TemplateResponse:
    """Create a template with a blank page and a starting layout."""
    return _template(await svc(c).create_template(actor.user_id, course_id, body.name))


@router.put(
    P + "/{course_id}/templates/{template_id}",
    operation_id="course_certificates_update_template",
)
async def update_template(
    course_id: UUID,
    template_id: UUID,
    body: TemplateUpdate,
    c: ContainerDep,
    actor: AnyActor,
) -> TemplateResponse:
    """Store the layout of a template."""
    row = await svc(c).update_template(
        actor.user_id, course_id, template_id, body.model_dump(mode="json")
    )
    return _template(row)


@router.delete(
    P + "/{course_id}/templates/{template_id}",
    operation_id="course_certificates_delete_template",
    status_code=204,
)
async def delete_template(
    course_id: UUID, template_id: UUID, c: ContainerDep, actor: AnyActor
) -> Response:
    """Delete a template."""
    await svc(c).delete_template(actor.user_id, course_id, template_id)
    return Response(status_code=204)


@router.post(
    P + "/{course_id}/templates/{template_id}/background",
    operation_id="course_certificates_upload_background",
)
async def upload_background(
    course_id: UUID,
    template_id: UUID,
    file: Annotated[UploadFile, File()],
    c: ContainerDep,
    actor: AnyActor,
) -> TemplateResponse:
    """Upload a background: PNG, JPEG or a PDF (first page), up to 10 MB."""
    data = await file.read(course_render.MAX_UPLOAD_BYTES + 1)
    row = await svc(c).upload_background(actor.user_id, course_id, template_id, data)
    return _template(row)


@router.get(
    P + "/{course_id}/templates/{template_id}/preview.png",
    operation_id="course_certificates_preview_template",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def preview_template(
    course_id: UUID,
    template_id: UUID,
    c: ContainerDep,
    actor: AnyActor,
    name: str | None = None,
) -> Response:
    """Return a PNG preview of the saved template with sample values."""
    png = await svc(c).preview(actor.user_id, course_id, template_id, name)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get(
    P + "/{course_id}/partners", operation_id="course_certificates_list_partners"
)
async def list_partners(
    course_id: UUID, c: ContainerDep, actor: AnyActor
) -> PartnerList:
    """Return the partners of a course."""
    rows = await svc(c).list_partners(actor.user_id, course_id)
    return PartnerList(items=[_partner(r) for r in rows])


@router.post(
    P + "/{course_id}/partners", operation_id="course_certificates_create_partner"
)
async def create_partner(
    course_id: UUID, body: PartnerBody, c: ContainerDep, actor: AnyActor
) -> PartnerResponse:
    """Add a partner."""
    row = await svc(c).save_partner(actor.user_id, course_id, None, body.model_dump())
    return _partner(row)


@router.put(
    P + "/{course_id}/partners/{partner_id}",
    operation_id="course_certificates_update_partner",
)
async def update_partner(
    course_id: UUID,
    partner_id: UUID,
    body: PartnerBody,
    c: ContainerDep,
    actor: AnyActor,
) -> PartnerResponse:
    """Update a partner."""
    row = await svc(c).save_partner(
        actor.user_id, course_id, partner_id, body.model_dump()
    )
    return _partner(row)


@router.delete(
    P + "/{course_id}/partners/{partner_id}",
    operation_id="course_certificates_delete_partner",
    status_code=204,
)
async def delete_partner(
    course_id: UUID, partner_id: UUID, c: ContainerDep, actor: AnyActor
) -> Response:
    """Delete a partner."""
    await svc(c).delete_partner(actor.user_id, course_id, partner_id)
    return Response(status_code=204)


@router.post(
    P + "/{course_id}/partners/{partner_id}/logo",
    operation_id="course_certificates_upload_partner_logo",
)
async def upload_logo(
    course_id: UUID,
    partner_id: UUID,
    file: Annotated[UploadFile, File()],
    c: ContainerDep,
    actor: AnyActor,
) -> PartnerResponse:
    """Upload a partner logo (PNG or JPEG)."""
    data = await file.read(course_render.MAX_UPLOAD_BYTES + 1)
    row = await svc(c).upload_logo(actor.user_id, course_id, partner_id, data)
    return _partner(row)


@router.get(P + "/{course_id}/issued", operation_id="course_certificates_list_issued")
async def list_issued(course_id: UUID, c: ContainerDep, actor: AnyActor) -> IssuedList:
    """Return the issued certificates of a course."""
    rows = await svc(c).list_issued(actor.user_id, course_id)
    return IssuedList(
        items=[
            IssuedItem(
                id=r.id,
                student=StudentRef(id=r.user_id, name=r.holder_name),
                tier=r.tier_key,
                issued_at=r.issued_at,
                code=r.code,
                revoked=r.revoked_at is not None,
            )
            for r in rows
        ]
    )


@router.post(
    P + "/{course_id}/issue-eligible", operation_id="course_certificates_issue_eligible"
)
async def issue_eligible(
    course_id: UUID, c: ContainerDep, actor: AnyActor
) -> IssueResult:
    """Issue certificates to every eligible learner now."""
    return IssueResult(issued=await svc(c).issue_eligible(actor.user_id, course_id))


@router.post(
    P + "/{course_id}/issued/{cert_id}/revoke",
    operation_id="course_certificates_revoke",
    status_code=204,
)
async def revoke(
    course_id: UUID, cert_id: UUID, body: RevokeBody, c: ContainerDep, actor: AnyActor
) -> Response:
    """Revoke a certificate."""
    await svc(c).revoke(actor.user_id, course_id, cert_id, body.reason)
    return Response(status_code=204)


def _mine(service: CourseCertificates, row: IssuedCertificate) -> MyCertificate:
    return MyCertificate(
        id=row.id,
        code=row.code,
        tier=Labels(**row.tier_label),
        issued_at=row.issued_at,
        verify_url=service.verify_url(row.code),
        pdf_url=f"{P}/issued/{row.id}/pdf",
        revoked=row.revoked_at is not None,
    )


@router.post(P + "/{course_id}/mine", operation_id="course_certificates_mine")
async def mine(course_id: UUID, c: ContainerDep, actor: AnyActor) -> MineResponse:
    """Evaluate the caller, issue the certificate when earned and return the status."""
    service = svc(c)
    status = await service.mine(actor.user_id, course_id)
    return MineResponse(
        eligible=status.eligible,
        progress_pct=status.progress_pct,
        passing_pct=status.passing_pct,
        next_tier=_tier(status.next_tier) if status.next_tier else None,
        certificate=_mine(service, status.certificate) if status.certificate else None,
        enabled=status.enabled,
        score_pct=status.score_pct,
        required_steps_left=status.required_steps_left,
    )


@router.get(
    P + "/issued/{cert_id}/pdf",
    operation_id="course_certificates_pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def pdf(cert_id: UUID, c: ContainerDep, actor: AnyActor) -> Response:
    """Download a certificate PDF (holder or course staff)."""
    name, data = await svc(c).pdf(actor.user_id, cert_id)
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# - - - Public (no sign-in) - - -


@router.get(
    "/v1/certificates/verify/{code}",
    operation_id="course_certificates_verify",
    dependencies=PUBLIC,
)
async def verify(code: str, c: ContainerDep) -> VerifyResponse:
    """Verify a certificate: holder name as printed, course, tier, partner, status."""
    row = await svc(c).verify(code)
    partner = row.partner
    return VerifyResponse(
        status="revoked" if row.revoked_at else "valid",
        holder_name=row.holder_name,
        course_title=row.course_title,
        tier_label=Labels(**row.tier_label),
        partner=(
            PublicPartner(
                name=partner["name"],
                url=partner.get("url"),
                logo_url=_logo_url(partner["id"], partner.get("logo_file_id")),
            )
            if partner
            else None
        ),
        issued_at=row.issued_at,
        qr_svg_url=f"/v1/certificates/verify/{row.code}/qr.svg",
    )


@router.get(
    "/v1/certificates/verify/{code}/qr.svg",
    operation_id="course_certificates_verify_qr",
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {}}}},
    dependencies=PUBLIC,
)
async def verify_qr(code: str, c: ContainerDep) -> Response:
    """Return the QR code of the verification page."""
    service = svc(c)
    row = await service.verify(code)
    svg = course_render.qr_svg(service.verify_url(row.code))
    return Response(svg, media_type="image/svg+xml", headers=IMAGE_CACHE)


@router.get(
    P + "/{course_id}/public",
    operation_id="course_certificates_public_info",
    dependencies=PUBLIC,
)
async def public_info(course_id: UUID, c: ContainerDep) -> PublicCourseInfo:
    """Certificate facts of a public course for its landing page."""
    settings, partners = await svc(c).public_info(course_id)
    return PublicCourseInfo(
        enabled=settings.enabled,
        passing_pct=settings.passing_pct,
        partners=[
            PublicPartner(
                name=p.name, url=p.url, logo_url=_logo_url(p.id, p.logo_file_id)
            )
            for p in partners
        ],
        tiers=[Labels(**t.label) for t in settings.tiers] if settings.enabled else [],
        sample_url=f"{P}/{course_id}/sample.png" if settings.enabled else None,
    )


@router.get(
    P + "/{course_id}/sample.png",
    operation_id="course_certificates_sample",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
    dependencies=PUBLIC,
)
async def sample(course_id: UUID, c: ContainerDep) -> Response:
    """A sample certificate of a public course."""
    png = await svc(c).sample(course_id)
    return Response(png, media_type="image/png", headers=IMAGE_CACHE)


@router.get(
    "/v1/certificates/templates/{template_id}/background.png",
    operation_id="course_certificates_background",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
    dependencies=PUBLIC,
)
async def background(
    template_id: UUID, c: ContainerDep, v: UUID | None = None
) -> Response:
    """Serve the template image of a public course, or by its versioned link."""
    png = await svc(c).background(template_id, v)
    return Response(png, media_type="image/png", headers=IMAGE_CACHE)


@router.get(
    "/v1/certificates/partners/{partner_id}/logo.png",
    operation_id="course_certificates_partner_logo",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
    dependencies=PUBLIC,
)
async def partner_logo(
    partner_id: UUID, c: ContainerDep, v: UUID | None = None
) -> Response:
    """A partner logo of a public course, or by its versioned link."""
    png = await svc(c).logo(partner_id, v)
    return Response(png, media_type="image/png", headers=IMAGE_CACHE)


@router.get(
    "/v1/certificates/fonts/{font}.woff2",
    operation_id="course_certificates_font",
    response_class=Response,
    responses={200: {"content": {"font/ttf": {}}}},
    dependencies=PUBLIC,
)
async def font(font: FontKey) -> Response:
    """Serve a bundled OFL typeface for the web constructor."""
    path = course_render.font_path(font)
    if path is None:
        raise CourseCertificateNotFoundError()
    return Response(
        path.read_bytes(),
        media_type="font/ttf",
        headers={"Cache-Control": "public, max-age=86400"},
    )


ROUTERS: list[APIRouter] = [router]
