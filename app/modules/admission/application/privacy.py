"""Purpose consents, export and erasure of my data, and who looked at it."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.staff import AuditRecord
from app.modules.admission.ports.consent import (
    AI,
    PURPOSES,
    SHARING,
    STAFF_VIEW,
    PurposeConsentStore,
    PurposeGrant,
)
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

AUDIT_LIMIT = 200
CASCADING = frozenset({STAFF_VIEW, SHARING})
"""Withdrawing one of these also ends guest links and helper access."""


@dataclass(frozen=True, slots=True)
class ConsentState:
    """The caller's purposes and the derived non-AI mode."""

    grants: list[PurposeGrant]
    non_ai_mode: bool


LOCALES: Final = ("uz", "ru", "en")


def describe_purposes(translate: Callable[[str, str], str]) -> list[dict[str, Any]]:
    """List the purposes with their texts per locale (`translate(locale, key)`)."""
    out: list[dict[str, Any]] = []
    for purpose in PURPOSES:
        stem = "admission-purpose-" + purpose.removeprefix("admission_").replace(
            "_", "-"
        )
        out.append(
            {
                "id": purpose,
                "title": {x: translate(x, f"{stem}-title") for x in LOCALES},
                "text": {x: translate(x, f"{stem}-text") for x in LOCALES},
            }
        )
    return out


class PrivacyService:
    """Everything the student controls about their admission data."""

    def __init__(
        self, uow_factory: UowFactory, consents: PurposeConsentStore, clock: Clock
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._consents = consents
        self._clock = clock

    async def consent(self, ctx: AdmissionContext) -> ConsentState:
        """Return the caller's purpose consents."""
        grants = await self._consents.grants_of(ctx.user_id)
        active = {g.purpose for g in grants if g.active}
        return ConsentState(grants, AI not in active)

    async def grant(self, ctx: AdmissionContext, purposes: list[str]) -> ConsentState:
        """Grant the purposes (known ones only)."""
        if not purposes or any(p not in PURPOSES for p in purposes):
            raise AdmissionNotFoundError()
        now = self._clock.now()
        for purpose in dict.fromkeys(purposes):
            await self._consents.grant(ctx.user_id, purpose, now=now)
            await self._audit(ctx, "consent.granted", {"purpose": purpose})
        return await self.consent(ctx)

    async def withdraw(self, ctx: AdmissionContext, purpose: str) -> ConsentState:
        """Withdraw a purpose; staff view and sharing also end shared access."""
        if purpose not in PURPOSES:
            raise AdmissionNotFoundError()
        now = self._clock.now()
        await self._consents.withdraw(ctx.user_id, purpose, now=now)
        async with self._uow() as uow:
            if purpose in CASCADING:
                await uow.privacy.revoke_sharing(ctx.user_id, now)
            uow.access.audit(
                AuditEvent(
                    action="consent.withdrawn",
                    actor_id=ctx.user_id,
                    student_id=ctx.user_id,
                    meta={"purpose": purpose},
                )
            )
            await uow.commit()
        return await self.consent(ctx)

    async def export(self, ctx: AdmissionContext) -> dict[str, Any]:
        """Return my rows per table and my access log; staff-only notes excluded."""
        async with self._uow() as uow:
            tables = await uow.privacy.export(ctx.user_id)
            log = await uow.privacy.audit(ctx.user_id, AUDIT_LIMIT)
            uow.access.audit(
                AuditEvent(
                    action="data.exported",
                    actor_id=ctx.user_id,
                    student_id=ctx.user_id,
                )
            )
            await uow.commit()
        return {
            "generated_at": self._clock.now(),
            "tables": tables,
            "access_log": log,
        }

    async def erase(self, ctx: AdmissionContext) -> dict[str, int]:
        """Delete my admission data and withdraw every purpose consent."""
        now = self._clock.now()
        async with self._uow() as uow:
            counts = await uow.privacy.erase(ctx.user_id)
            uow.access.audit(
                AuditEvent(
                    action="data.erased",
                    actor_id=ctx.user_id,
                    student_id=ctx.user_id,
                    meta={"tables": len(counts)},
                )
            )
            await uow.commit()
        for purpose in PURPOSES:
            await self._consents.withdraw(ctx.user_id, purpose, now=now)
        return counts

    async def audit(self, ctx: AdmissionContext) -> list[AuditRecord]:
        """Return who looked at my data, newest first."""
        async with self._uow() as uow:
            return await uow.privacy.audit(ctx.user_id, AUDIT_LIMIT)

    async def _audit(
        self, ctx: AdmissionContext, action: str, meta: dict[str, Any]
    ) -> None:
        async with self._uow() as uow:
            uow.access.audit(
                AuditEvent(
                    action=action,
                    actor_id=ctx.user_id,
                    student_id=ctx.user_id,
                    meta=meta,
                )
            )
            await uow.commit()
