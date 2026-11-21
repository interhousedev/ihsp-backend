"""Honor suggestions from the student's platform certificates.

Standard exams (SAT, IELTS ...) belong to the test scores; every other certificate
of the student (olympiads, medals ...) is offered as an honor until one is made
from it. A dismissed one leaves the suggestion row but stays in the pick list of the
creation dialog.
"""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.items import (
    HONOR_DESCRIPTION_MAX,
    RECOGNITION_LEVELS,
    TITLE_MAX,
)
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.contracts.certificates import CertificateDirectory, StudentCertificate
from app.shared.honor_categories import HONOR_CATEGORIES

_LEVELS: Final = {
    "school": "school",
    "local": "regional",
    "regional": "regional",
    "republican": "national",
    "national": "national",
    "international": "international",
}
_FACTS: Final = ("level", "score", "percent", "subject", "year")


@dataclass(frozen=True, slots=True)
class HonorSuggestion:
    """A certificate with the honor fields it would prefill."""

    entry_id: UUID
    name: str
    title: str
    description: str
    category: str
    level: str | None
    issued_at: str | None
    dismissed: bool


@dataclass(frozen=True, slots=True)
class HonorSuggestions:
    """The suggestion row and the full pick list of the creation dialog."""

    suggested: list[HonorSuggestion]
    available: list[HonorSuggestion]


def prefill(cert: StudentCertificate, locale: str, dismissed: bool) -> HonorSuggestion:
    """Map a certificate to the honor fields it prefills (texts stay English)."""
    english = cert.names.get("en") or cert.type_code
    subject = cert.values.get("subject")
    title = f"{english}: {subject}" if isinstance(subject, str) and subject else english
    raw_level = str(cert.values.get("level") or "").strip().lower()
    facts = [
        f"{key.capitalize()}: {cert.values[key]}"
        for key in _FACTS
        if cert.values.get(key) not in (None, "", [])
    ]
    category = cert.category if cert.category in HONOR_CATEGORIES else "other"
    level = _LEVELS.get(raw_level)
    return HonorSuggestion(
        entry_id=cert.entry_id,
        name=cert.name(locale),
        title=title[:TITLE_MAX].strip(),
        description=", ".join(facts)[:HONOR_DESCRIPTION_MAX].strip(", "),
        category=category,
        level=level if level in RECOGNITION_LEVELS else None,
        issued_at=cert.issued_at.isoformat() if cert.issued_at else None,
        dismissed=dismissed,
    )


class HonorSuggestionService:
    """List and dismiss the honor suggestions of the caller."""

    def __init__(
        self,
        uow_factory: UowFactory,
        access: AccessPolicy,
        certificates: CertificateDirectory | None,
    ) -> None:
        """Keep the collaborators; without a directory nothing is suggested."""
        self._uow = uow_factory
        self._access = access
        self._certificates = certificates

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "activities:edit"})

    async def _open(
        self, ctx: AdmissionContext
    ) -> tuple[list[StudentCertificate], set[UUID], set[UUID]]:
        if self._certificates is None:
            return [], set(), set()
        certs = [
            c
            for c in await self._certificates.for_student(ctx.user_id)
            if not c.standard
        ]
        async with self._uow() as uow:
            items = await uow.items.list_for(ctx.user_id)
            dismissed = await uow.items.dismissed_certificates(ctx.user_id)
            await uow.commit()
        linked = {i.certificate_entry_id for i in items if i.certificate_entry_id}
        return [c for c in certs if c.entry_id not in linked], dismissed, linked

    async def suggestions(self, ctx: AdmissionContext, locale: str) -> HonorSuggestions:
        """Non-standard certificates not yet used for an honor."""
        await self._owner(ctx)
        certs, dismissed, _ = await self._open(ctx)
        every = [prefill(c, locale, c.entry_id in dismissed) for c in certs]
        return HonorSuggestions([s for s in every if not s.dismissed], every)

    async def dismiss(self, ctx: AdmissionContext, entry_id: UUID) -> None:
        """Hide a suggestion; it stays in the creation pick list."""
        await self._owner(ctx)
        certs, _, _ = await self._open(ctx)
        if entry_id not in {c.entry_id for c in certs}:
            raise AdmissionNotFoundError()
        async with self._uow() as uow:
            await uow.items.dismiss_certificate(ctx.user_id, entry_id)
            await uow.commit()
