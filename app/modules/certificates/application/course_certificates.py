"""Use cases of course certificates: design, tiers, partners, issuing, verifying.

Every use case maps rows to the values of ``domain.course.values`` inside its unit
of work, before commit; no ORM object is returned.
"""

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.certificates.domain.course.rules import (
    CertificateSettings,
    Evaluation,
    SectionResult,
    Tier,
    apply_settings,
    default_fields,
    evaluate,
    new_code,
    parse_fields,
    parse_qr,
    parse_tiers,
    partner_values,
    tier_rank,
)
from app.modules.certificates.domain.course.values import (
    CertificateTemplate,
    CoursePartner,
    IssuedCertificate,
)
from app.modules.certificates.domain.errors import (
    CourseCertificateForbiddenError,
    CourseCertificateInvalidError,
    CourseCertificateNotEligibleError,
    CourseCertificateNotFoundError,
)
from app.modules.certificates.infrastructure import course_render
from app.modules.certificates.infrastructure.course_store import (
    SqlCourseCertificatesUnitOfWork,
    to_issued,
    to_partner,
    to_template,
)
from app.modules.certificates.infrastructure.orm.course_certificate import (
    CourseCertificateSettingsRow,
    CourseCertificateTemplateRow,
    CoursePartnerRow,
    IssuedCourseCertificateRow,
)
from app.shared.clock import Clock, local_today
from app.shared.contracts.course_certificates import CourseCertificateFacts
from app.shared.contracts.files import FilePurpose, FilesApi, FileScope
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id

from sqlalchemy.exc import IntegrityError

UowFactory = Callable[[], SqlCourseCertificatesUnitOfWork]

# Sample certificates rendered per (course, design hash); oldest dropped first.
SAMPLE_CACHE_SIZE = 64


@dataclass(frozen=True, slots=True)
class LearnerStatus:
    """Where a learner stands and the certificate they hold."""

    eligible: bool
    progress_pct: int
    passing_pct: int
    next_tier: Tier | None
    certificate: IssuedCertificate | None
    enabled: bool = True
    score_pct: int = 0
    required_steps_left: int = 0


def to_settings(
    course_id: UUID, row: CourseCertificateSettingsRow | None
) -> CertificateSettings:
    """Return the domain settings of a row (defaults when there is none)."""
    if row is None:
        return CertificateSettings(course_id=course_id)
    return CertificateSettings(
        course_id=course_id,
        enabled=row.enabled,
        passing_pct=row.passing_pct,
        optional_section_ids=tuple(row.optional_section_ids),
        tiers=parse_tiers(row.tiers),
        template_id=row.template_id,
        partner_ids=tuple(UUID(p) for p in row.partner_ids),
    )


def holder_name(first: str, last: str) -> str:
    """Return the name as printed: first name, then last name."""
    return " ".join(part for part in (first.strip(), last.strip()) if part)


class CourseCertificates:
    """Every course certificate use case over one store."""

    def __init__(
        self,
        uow_factory: UowFactory,
        facts: CourseCertificateFacts,
        files: FilesApi,
        directory: IdentityDirectory,
        clock: Clock,
        verify_base: str,
    ) -> None:
        """Keep the collaborators; ``verify_base`` is the LMS web origin."""
        self._uow = uow_factory
        self._facts = facts
        self._files = files
        self._directory = directory
        self._clock = clock
        self._verify_base = verify_base.rstrip("/")
        self._samples: OrderedDict[tuple[UUID, str], bytes] = OrderedDict()

    def verify_url(self, code: str) -> str:
        """Return the public verification page of a code."""
        return f"{self._verify_base}/verify/?code={code}"

    async def require_manager(self, user_id: UUID, course_id: UUID) -> None:
        """Raise unless the user may edit the course."""
        if not await self._facts.can_manage(user_id, course_id):
            raise CourseCertificateForbiddenError()

    # - - - Settings - - -

    async def get_settings(self, user_id: UUID, course_id: UUID) -> CertificateSettings:
        """Return the settings of a course (staff)."""
        await self.require_manager(user_id, course_id)
        async with self._uow() as uow:
            return to_settings(course_id, await uow.settings(course_id))

    async def put_settings(
        self, user_id: UUID, course_id: UUID, raw: dict[str, Any]
    ) -> CertificateSettings:
        """Validate and store the settings of a course (staff)."""
        await self.require_manager(user_id, course_id)
        value = apply_settings(CertificateSettings(course_id=course_id), raw)
        async with self._uow() as uow:
            if value.template_id is not None:
                template = await uow.template(value.template_id)
                if template is None or template.course_id != course_id:
                    raise CourseCertificateInvalidError(params={"field": "template_id"})
            known = {p.id for p in await uow.partners(course_id)}
            if any(p not in known for p in value.partner_ids):
                raise CourseCertificateInvalidError(params={"field": "partner_ids"})
            row = await uow.settings(course_id)
            if row is None:
                row = CourseCertificateSettingsRow(course_id=course_id)
                uow.add(row)
            row.enabled = value.enabled
            row.passing_pct = value.passing_pct
            row.optional_section_ids = list(value.optional_section_ids)
            row.tiers = [t.to_dict() for t in value.tiers]
            row.template_id = value.template_id
            row.partner_ids = [str(p) for p in value.partner_ids]
            await uow.commit()
        return value

    # - - - Templates - - -

    async def list_templates(
        self, user_id: UUID, course_id: UUID
    ) -> list[CertificateTemplate]:
        """Return the templates of a course (staff)."""
        await self.require_manager(user_id, course_id)
        async with self._uow() as uow:
            return [to_template(r) for r in await uow.templates(course_id)]

    async def create_template(
        self, user_id: UUID, course_id: UUID, name: str
    ) -> CertificateTemplate:
        """Create a template with a blank A4 page and a starting layout."""
        await self.require_manager(user_id, course_id)
        name = name.strip()
        if not name or len(name) > 120:
            raise CourseCertificateInvalidError(params={"field": "name"})
        width, height = course_render.BLANK_SIZE
        row = CourseCertificateTemplateRow(
            id=new_id(),
            course_id=course_id,
            name=name,
            background_file_id=None,
            width_px=width,
            height_px=height,
            fields=default_fields(),
            qr=parse_qr(None),
        )
        async with self._uow() as uow:
            if len(await uow.templates(course_id)) >= 20:
                raise CourseCertificateInvalidError(params={"field": "templates"})
            uow.add(row)
            value = to_template(row)
            await uow.commit()
        return value

    async def _own_template(
        self, uow: SqlCourseCertificatesUnitOfWork, course_id: UUID, template_id: UUID
    ) -> CourseCertificateTemplateRow:
        row = await uow.template(template_id)
        if row is None or row.course_id != course_id:
            raise CourseCertificateNotFoundError()
        return row

    async def update_template(
        self, user_id: UUID, course_id: UUID, template_id: UUID, raw: dict[str, Any]
    ) -> CertificateTemplate:
        """Store a new name, field layout and QR style."""
        await self.require_manager(user_id, course_id)
        name = str(raw.get("name") or "").strip()
        if not name or len(name) > 120:
            raise CourseCertificateInvalidError(params={"field": "name"})
        fields = parse_fields(raw.get("fields") or [])
        qr = parse_qr(raw.get("qr"))
        async with self._uow() as uow:
            row = await self._own_template(uow, course_id, template_id)
            row.name, row.fields, row.qr = name, fields, qr
            value = to_template(row)
            await uow.commit()
        return value

    async def delete_template(
        self, user_id: UUID, course_id: UUID, template_id: UUID
    ) -> None:
        """Delete a template (issued certificates keep their snapshot)."""
        await self.require_manager(user_id, course_id)
        async with self._uow() as uow:
            row = await self._own_template(uow, course_id, template_id)
            settings = await uow.settings(course_id)
            if settings is not None:
                if settings.template_id == template_id:
                    settings.template_id = None
                settings.tiers = [
                    t
                    for t in settings.tiers
                    if t.get("template_id") != str(template_id)
                ]
            await uow.delete(row)
            await uow.commit()

    async def upload_background(
        self, user_id: UUID, course_id: UUID, template_id: UUID, data: bytes
    ) -> CertificateTemplate:
        """Check, normalise and store a background (PNG, JPEG or a PDF page)."""
        await self.require_manager(user_id, course_id)
        png, width, height = course_render.normalize_image(data)
        stored = await self._files.store_bytes(
            owner_id=user_id,
            scope=FileScope.COURSE,
            purpose=FilePurpose.CERTIFICATE,
            name="certificate-background.png",
            data=png,
        )
        async with self._uow() as uow:
            row = await self._own_template(uow, course_id, template_id)
            row.background_file_id = stored.id
            row.width_px, row.height_px = width, height
            value = to_template(row)
            await uow.commit()
        return value

    async def background(self, template_id: UUID, version: UUID | None) -> bytes:
        """Return the template image.

        Anonymous callers get it for a public course with certificates on; the
        link handed to staff carries the file id (``version``), which also opens it.
        """
        async with self._uow() as uow:
            row = await uow.template(template_id)
            course_id = row.course_id if row is not None else None
            file_id = row.background_file_id if row is not None else None
        if course_id is None or file_id is None:
            raise CourseCertificateNotFoundError()
        if version != file_id:
            await self._public_enabled(course_id)
        return await self._files.read_bytes(file_id)

    async def preview(
        self, user_id: UUID, course_id: UUID, template_id: UUID, name: str | None
    ) -> bytes:
        """Return a PNG preview of a template with sample values (staff)."""
        await self.require_manager(user_id, course_id)
        async with self._uow() as uow:
            row = await self._own_template(uow, course_id, template_id)
            snapshot = _snapshot(row)
            settings = to_settings(course_id, await uow.settings(course_id))
            partner = await self._partner(uow, settings)
        course = await self._facts.course(course_id)
        return await self._draw_png(
            snapshot,
            {
                "name": (name or "").strip()[:120] or "Alisher Abdullayev",
                "course": course.title if course else "",
                "tier": settings.tiers[-1].label["en"],
                "date": local_today(self._clock).strftime("%d.%m.%Y"),
                "partner": partner["name"] if partner else "",
                "code": "SAMPLE000000",
            },
            self.verify_url("SAMPLE000000"),
            partner,
        )

    # - - - Partners - - -

    async def list_partners(
        self, user_id: UUID | None, course_id: UUID
    ) -> list[CoursePartner]:
        """Return the partners of a course (staff when ``user_id`` is given)."""
        if user_id is not None:
            await self.require_manager(user_id, course_id)
        async with self._uow() as uow:
            return [to_partner(r) for r in await uow.partners(course_id)]

    async def save_partner(
        self,
        user_id: UUID,
        course_id: UUID,
        partner_id: UUID | None,
        raw: dict[str, Any],
    ) -> CoursePartner:
        """Create or update a partner."""
        await self.require_manager(user_id, course_id)
        values = partner_values(raw)
        async with self._uow() as uow:
            if partner_id is None:
                if len(await uow.partners(course_id)) >= 10:
                    raise CourseCertificateInvalidError(params={"field": "partners"})
                row = CoursePartnerRow(
                    id=new_id(), course_id=course_id, logo_file_id=None, **values
                )
                uow.add(row)
            else:
                found = await uow.partner(partner_id)
                if found is None or found.course_id != course_id:
                    raise CourseCertificateNotFoundError()
                row = found
                row.name, row.url = values["name"], values["url"]
                row.co_issued = values["co_issued"]
            value = to_partner(row)
            await uow.commit()
        return value

    async def delete_partner(
        self, user_id: UUID, course_id: UUID, partner_id: UUID
    ) -> None:
        """Delete a partner and drop it from the settings."""
        await self.require_manager(user_id, course_id)
        async with self._uow() as uow:
            row = await uow.partner(partner_id)
            if row is None or row.course_id != course_id:
                raise CourseCertificateNotFoundError()
            settings = await uow.settings(course_id)
            if settings is not None:
                settings.partner_ids = [
                    p for p in settings.partner_ids if p != str(partner_id)
                ]
            await uow.delete(row)
            await uow.commit()

    async def upload_logo(
        self, user_id: UUID, course_id: UUID, partner_id: UUID, data: bytes
    ) -> CoursePartner:
        """Check and store a partner logo (PNG or JPEG, scaled to 800 px)."""
        await self.require_manager(user_id, course_id)
        png, _, _ = course_render.normalize_image(data, max_side=800)
        stored = await self._files.store_bytes(
            owner_id=user_id,
            scope=FileScope.COURSE,
            purpose=FilePurpose.CERTIFICATE,
            name="partner-logo.png",
            data=png,
        )
        async with self._uow() as uow:
            row = await uow.partner(partner_id)
            if row is None or row.course_id != course_id:
                raise CourseCertificateNotFoundError()
            row.logo_file_id = stored.id
            value = to_partner(row)
            await uow.commit()
        return value

    async def logo(self, partner_id: UUID, version: UUID | None) -> bytes:
        """Return the partner image; access as for ``background``."""
        async with self._uow() as uow:
            row = await uow.partner(partner_id)
            course_id = row.course_id if row is not None else None
            file_id = row.logo_file_id if row is not None else None
        if course_id is None or file_id is None:
            raise CourseCertificateNotFoundError()
        if version != file_id:
            await self._public_enabled(course_id)
        return await self._files.read_bytes(file_id)

    async def _partner(
        self, uow: SqlCourseCertificatesUnitOfWork, settings: CertificateSettings
    ) -> dict[str, Any] | None:
        """Return the first co-issuing partner chosen in the settings."""
        for partner_id in settings.partner_ids:
            row = await uow.partner(partner_id)
            if row is not None and row.co_issued:
                return {
                    "id": str(row.id),
                    "name": row.name,
                    "url": row.url,
                    "logo_file_id": (
                        str(row.logo_file_id) if row.logo_file_id else None
                    ),
                }
        return None

    # - - - Issuing - - -

    async def evaluate_learner(
        self, course_id: UUID, user_id: UUID
    ) -> tuple[CertificateSettings, Evaluation | None, int]:
        """Return the settings, the evaluation (None if not enrolled) and progress."""
        async with self._uow() as uow:
            settings = to_settings(course_id, await uow.settings(course_id))
        result = await self._facts.learner(course_id, user_id)
        if result is None:
            return settings, None, 0
        sections = [
            SectionResult(
                s.section_id,
                s.steps_total,
                s.steps_done,
                s.points_total,
                s.points_earned,
            )
            for s in result.sections
        ]
        return settings, evaluate(settings, sections), result.progress_pct

    async def _held(self, course_id: UUID, user_id: UUID) -> IssuedCertificate | None:
        async with self._uow() as uow:
            row = await uow.issued_for(course_id, user_id)
            return to_issued(row) if row is not None else None

    async def issue_if_eligible(
        self, course_id: UUID, user_id: UUID
    ) -> IssuedCertificate | None:
        """Issue or upgrade the learner's certificate; idempotent.

        One certificate per learner and course: a second call returns the same one,
        a higher tier upgrades it in place (same code), a lower one never downgrades,
        a revoked certificate is never re-issued automatically.
        """
        settings, evaluation, _ = await self.evaluate_learner(course_id, user_id)
        if not settings.enabled or evaluation is None or evaluation.tier is None:
            return await self._held(course_id, user_id)
        tier = evaluation.tier
        course = await self._facts.course(course_id)
        user = await self._directory.get_user(user_id)
        if course is None or user is None:
            return None
        async with self._uow() as uow:
            current = await uow.issued_for(course_id, user_id, lock=True)
            if current is not None:
                if current.revoked_at is None and tier_rank(
                    settings, tier.key
                ) > tier_rank(settings, current.tier_key):
                    current.tier_key, current.tier_label = tier.key, dict(tier.label)
                    current.score_pct = evaluation.score_pct
                    current.template = await self._template_snapshot(uow, settings)
                value = to_issued(current)
                await uow.commit()
                return value
            row = IssuedCourseCertificateRow(
                id=new_id(),
                code=new_code(),
                course_id=course_id,
                user_id=user_id,
                tier_key=tier.key,
                tier_label=dict(tier.label),
                holder_name=holder_name(user.first_name, user.last_name)[:240],
                course_title=course.title[:300],
                partner=await self._partner(uow, settings),
                template=await self._template_snapshot(uow, settings),
                score_pct=evaluation.score_pct,
                issued_at=self._clock.now(),
                revoked_at=None,
                revoke_reason=None,
            )
            uow.add(row)
            value = to_issued(row)
            try:
                await uow.commit()
            except IntegrityError:
                pass  # a concurrent call issued it first
            else:
                return value
        return await self._held(course_id, user_id)

    async def _template_snapshot(
        self, uow: SqlCourseCertificatesUnitOfWork, settings: CertificateSettings
    ) -> dict[str, Any] | None:
        if settings.template_id is None:
            return None
        row = await uow.template(settings.template_id)
        return _snapshot(row) if row is not None else None

    async def mine(self, user_id: UUID, course_id: UUID) -> LearnerStatus:
        """Evaluate the caller, issue when eligible and return the status."""
        settings, evaluation, progress = await self.evaluate_learner(course_id, user_id)
        if evaluation is None:
            raise CourseCertificateNotFoundError()
        certificate = await self.issue_if_eligible(course_id, user_id)
        return LearnerStatus(
            eligible=settings.enabled and evaluation.passed,
            progress_pct=progress,
            passing_pct=settings.passing_pct,
            next_tier=evaluation.next_tier,
            certificate=certificate,
            enabled=settings.enabled,
            score_pct=evaluation.score_pct,
            required_steps_left=evaluation.required_steps_left,
        )

    async def issue_eligible(self, user_id: UUID, course_id: UUID) -> int:
        """Issue to every eligible learner (staff); return how many hold one now."""
        await self.require_manager(user_id, course_id)
        return await self._issue_course(course_id)

    async def _issue_course(self, course_id: UUID) -> int:
        count = 0
        for learner in await self._facts.active_learners(course_id):
            held = await self.issue_if_eligible(course_id, learner)
            if held is not None and held.revoked_at is None:
                count += 1
        return count

    async def sweep(self) -> int:
        """Issue in every course with certificates on (periodic job)."""
        async with self._uow() as uow:
            courses = [row.course_id for row in await uow.enabled_courses()]
        return sum([await self._issue_course(c) for c in courses])

    async def list_issued(
        self, user_id: UUID, course_id: UUID
    ) -> list[IssuedCertificate]:
        """Return the certificates of a course (staff)."""
        await self.require_manager(user_id, course_id)
        async with self._uow() as uow:
            return [to_issued(r) for r in await uow.issued_in(course_id)]

    async def revoke(
        self, user_id: UUID, course_id: UUID, cert_id: UUID, reason: str
    ) -> IssuedCertificate:
        """Revoke a certificate; the verify page then shows it as revoked."""
        await self.require_manager(user_id, course_id)
        reason = reason.strip()
        if not reason or len(reason) > 500:
            raise CourseCertificateInvalidError(params={"field": "reason"})
        async with self._uow() as uow:
            row = await uow.issued(cert_id)
            if row is None or row.course_id != course_id:
                raise CourseCertificateNotFoundError()
            if row.revoked_at is None:
                row.revoked_at, row.revoke_reason = self._clock.now(), reason
            value = to_issued(row)
            await uow.commit()
        return value

    async def pdf(self, user_id: UUID, cert_id: UUID) -> tuple[str, bytes]:
        """Return the file name and PDF of a certificate (holder or course staff)."""
        async with self._uow() as uow:
            row = await uow.issued(cert_id)
            cert = to_issued(row) if row is not None else None
        if cert is None:
            raise CourseCertificateNotFoundError()
        if cert.user_id != user_id and not await self._facts.can_manage(
            user_id, cert.course_id
        ):
            raise CourseCertificateNotFoundError()
        if cert.revoked_at is not None:
            raise CourseCertificateNotEligibleError()
        image = await self._draw(
            cert.template or {"fields": default_fields(), "qr": parse_qr(None)},
            self._values(cert),
            self.verify_url(cert.code),
            cert.partner,
        )
        return f"certificate-{cert.code}.pdf", course_render.to_pdf(image)

    # - - - Public - - -

    async def verify(self, code: str) -> IssuedCertificate:
        """Return a certificate by its code (public; callers print minimal data)."""
        code = code.strip().upper()
        if not code.isalnum() or len(code) > 16:
            raise CourseCertificateNotFoundError()
        async with self._uow() as uow:
            row = await uow.issued_by_code(code)
            cert = to_issued(row) if row is not None else None
        if cert is None:
            raise CourseCertificateNotFoundError()
        return cert

    async def public_info(
        self, course_id: UUID
    ) -> tuple[CertificateSettings, list[CoursePartner]]:
        """Return the settings and every partner of a public course.

        The course page lists all attached partners; ``partner_ids`` and
        ``co_issued`` only decide what the certificate shows.
        """
        course = await self._facts.course(course_id)
        if course is None or not course.public:
            raise CourseCertificateNotFoundError()
        async with self._uow() as uow:
            settings = to_settings(course_id, await uow.settings(course_id))
            partners = [to_partner(p) for p in await uow.partners(course_id)]
        return settings, partners

    async def _public_enabled(self, course_id: UUID) -> CertificateSettings:
        """Return the settings; not found unless the course is public and enabled."""
        settings, _ = await self.public_info(course_id)
        if not settings.enabled:
            raise CourseCertificateNotFoundError()
        return settings

    async def sample(self, course_id: UUID) -> bytes:
        """Return a sample certificate PNG of a public course (cached per design)."""
        settings = await self._public_enabled(course_id)
        course = await self._facts.course(course_id)
        async with self._uow() as uow:
            snapshot = await self._template_snapshot(uow, settings)
            partner = await self._partner(uow, settings)
        design = snapshot or {"fields": default_fields(), "qr": parse_qr(None)}
        values = {
            "name": "—",
            "course": course.title if course else "",
            "tier": settings.tiers[0].label["en"],
            "date": local_today(self._clock).strftime("%d.%m.%Y"),
            "partner": partner["name"] if partner else "",
            "code": "SAMPLE000000",
        }
        version = hashlib.sha256(
            json.dumps([design, values, partner], sort_keys=True, default=str).encode()
        ).hexdigest()
        key = (course_id, version)
        cached = self._samples.get(key)
        if cached is not None:
            self._samples.move_to_end(key)
            return cached
        png = await self._draw_png(
            design, values, self.verify_url("SAMPLE000000"), partner
        )
        self._samples[key] = png
        if len(self._samples) > SAMPLE_CACHE_SIZE:
            self._samples.popitem(last=False)
        return png

    def _values(self, cert: IssuedCertificate) -> dict[str, str]:
        return {
            "name": cert.holder_name,
            "course": cert.course_title,
            "tier": cert.tier_label.get("en", cert.tier_key),
            "date": cert.issued_at.date().strftime("%d.%m.%Y"),
            "partner": (cert.partner or {}).get("name", ""),
            "code": cert.code,
        }

    async def _draw(
        self,
        snapshot: dict[str, Any],
        values: dict[str, str],
        url: str,
        partner: dict[str, Any] | None,
    ) -> Any:  # noqa: ANN401 — a Pillow image
        background = None
        if snapshot.get("background_file_id"):
            background = await self._files.read_bytes(
                UUID(snapshot["background_file_id"])
            )
        logo = None
        if partner and partner.get("logo_file_id"):
            logo = await self._files.read_bytes(UUID(partner["logo_file_id"]))
        return course_render.render(snapshot, background, values, url, logo)

    async def _draw_png(
        self,
        snapshot: dict[str, Any],
        values: dict[str, str],
        url: str,
        partner: dict[str, Any] | None,
    ) -> bytes:
        return course_render.to_png(await self._draw(snapshot, values, url, partner))


def _snapshot(row: CourseCertificateTemplateRow) -> dict[str, Any]:
    return {
        "background_file_id": (
            str(row.background_file_id) if row.background_file_id else None
        ),
        "width_px": row.width_px,
        "height_px": row.height_px,
        "fields": row.fields,
        "qr": row.qr,
    }
