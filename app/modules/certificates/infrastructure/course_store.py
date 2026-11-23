"""SQL unit of work for course certificates and the row-to-value mappers.

Use cases map rows with ``to_template``, ``to_partner`` and ``to_issued`` inside
the unit of work, before commit: no ORM object leaves the session.
"""

from uuid import UUID

from app.modules.certificates.domain.course.values import (
    CertificateTemplate,
    CoursePartner,
    IssuedCertificate,
)
from app.modules.certificates.infrastructure.orm.course_certificate import (
    CourseCertificateSettingsRow,
    CourseCertificateTemplateRow,
    CoursePartnerRow,
    IssuedCourseCertificateRow,
)
from app.shared.db.uow import SqlUnitOfWork

from sqlalchemy import select


def to_template(row: CourseCertificateTemplateRow) -> CertificateTemplate:
    """Return the value of a template row."""
    return CertificateTemplate(
        id=row.id,
        course_id=row.course_id,
        name=row.name,
        background_file_id=row.background_file_id,
        width_px=row.width_px,
        height_px=row.height_px,
        fields=list(row.fields),
        qr=dict(row.qr),
    )


def to_partner(row: CoursePartnerRow) -> CoursePartner:
    """Return the value of a partner row."""
    return CoursePartner(
        id=row.id,
        course_id=row.course_id,
        name=row.name,
        url=row.url,
        logo_file_id=row.logo_file_id,
        co_issued=bool(row.co_issued),
    )


def to_issued(row: IssuedCourseCertificateRow) -> IssuedCertificate:
    """Return the value of an issued certificate row."""
    return IssuedCertificate(
        id=row.id,
        code=row.code,
        course_id=row.course_id,
        user_id=row.user_id,
        tier_key=row.tier_key,
        tier_label=dict(row.tier_label),
        holder_name=row.holder_name,
        course_title=row.course_title,
        partner=dict(row.partner) if row.partner else None,
        template=dict(row.template) if row.template else None,
        score_pct=row.score_pct,
        issued_at=row.issued_at,
        revoked_at=row.revoked_at,
        revoke_reason=row.revoke_reason,
    )


class SqlCourseCertificatesUnitOfWork(SqlUnitOfWork):
    """One transaction over settings, templates, partners and issued certificates."""

    async def settings(self, course_id: UUID) -> CourseCertificateSettingsRow | None:
        """Return the settings row of a course."""
        return await self.session.get(CourseCertificateSettingsRow, course_id)

    def add(self, row: object) -> None:
        """Stage a new row."""
        self.session.add(row)

    async def delete(self, row: object) -> None:
        """Delete a row."""
        await self.session.delete(row)

    async def template(self, template_id: UUID) -> CourseCertificateTemplateRow | None:
        """Return a template."""
        return await self.session.get(CourseCertificateTemplateRow, template_id)

    async def templates(self, course_id: UUID) -> list[CourseCertificateTemplateRow]:
        """Return the templates of a course, oldest first."""
        rows = await self.session.scalars(
            select(CourseCertificateTemplateRow)
            .where(CourseCertificateTemplateRow.course_id == course_id)
            .order_by(CourseCertificateTemplateRow.created_at)
        )
        return list(rows)

    async def partner(self, partner_id: UUID) -> CoursePartnerRow | None:
        """Return a partner."""
        return await self.session.get(CoursePartnerRow, partner_id)

    async def partners(self, course_id: UUID) -> list[CoursePartnerRow]:
        """Return the partners of a course, oldest first."""
        rows = await self.session.scalars(
            select(CoursePartnerRow)
            .where(CoursePartnerRow.course_id == course_id)
            .order_by(CoursePartnerRow.created_at)
        )
        return list(rows)

    async def issued(self, cert_id: UUID) -> IssuedCourseCertificateRow | None:
        """Return an issued certificate."""
        return await self.session.get(IssuedCourseCertificateRow, cert_id)

    async def issued_for(
        self, course_id: UUID, user_id: UUID, *, lock: bool = False
    ) -> IssuedCourseCertificateRow | None:
        """Return the certificate of a learner in a course."""
        query = select(IssuedCourseCertificateRow).where(
            IssuedCourseCertificateRow.course_id == course_id,
            IssuedCourseCertificateRow.user_id == user_id,
        )
        if lock:
            query = query.with_for_update()
        row: IssuedCourseCertificateRow | None = await self.session.scalar(query)
        return row

    async def issued_by_code(self, code: str) -> IssuedCourseCertificateRow | None:
        """Return the certificate with a verification code."""
        row: IssuedCourseCertificateRow | None = await self.session.scalar(
            select(IssuedCourseCertificateRow).where(
                IssuedCourseCertificateRow.code == code
            )
        )
        return row

    async def issued_in(self, course_id: UUID) -> list[IssuedCourseCertificateRow]:
        """Return the certificates of a course, newest first."""
        rows = await self.session.scalars(
            select(IssuedCourseCertificateRow)
            .where(IssuedCourseCertificateRow.course_id == course_id)
            .order_by(IssuedCourseCertificateRow.issued_at.desc())
        )
        return list(rows)

    async def enabled_courses(self) -> list[CourseCertificateSettingsRow]:
        """Return the settings of every course with certificates on."""
        rows = await self.session.scalars(
            select(CourseCertificateSettingsRow).where(
                CourseCertificateSettingsRow.enabled.is_(True)
            )
        )
        return list(rows)

    async def flush(self) -> None:
        """Write staged rows (raises on a unique violation)."""
        await self.session.flush()
