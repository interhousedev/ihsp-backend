"""A signed-in user accepts the current versions."""

from collections.abc import Iterable, Sequence
from uuid import UUID

from app.modules.legal.application.queries import PendingItem, pending_for
from app.modules.legal.domain.errors import (
    LegalGuardianAttestationRequiredError,
    LegalStaleVersionError,
)
from app.modules.legal.domain.models import Acceptance, guardian_attestation_required
from app.modules.legal.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.legal import GLOBAL_APP, LegalItem
from app.shared.ids import new_id


class AcceptDocuments:
    """Record acceptances of the versions that are current right now."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self,
        user_id: UUID,
        items: Sequence[LegalItem],
        *,
        ip: str | None,
        user_agent: str | None,
        app: str = GLOBAL_APP,
        roles: Iterable[str] = (),
        guardian_attested: bool = False,
    ) -> list[PendingItem]:
        """Accept the items and return what is still pending for ``app``.

        Accepting an app-scoped document needs a guardian's attestation from any
        account that is not staff (``guardian_attestation_required``).

        Raises:
            LegalStaleVersionError: An item is not the current version of its kind
                and scope (nothing is recorded).
            LegalGuardianAttestationRequiredError: Attestation is required and not
                given (nothing is recorded).
        """
        now = self._clock.now()
        scoped = any(i.app_scope != GLOBAL_APP for i in items)
        if scoped and not guardian_attested and guardian_attestation_required(roles):
            raise LegalGuardianAttestationRequiredError()
        async with self._uow_factory() as uow:
            current = {
                (d.kind, d.app_scope): d.version for d in await uow.legal.list_current()
            }
            for item in items:
                found = current.get((item.kind, item.app_scope))
                if found != item.version:
                    raise LegalStaleVersionError(
                        params={"kind": item.kind, "current": found or 0}
                    )
            await uow.legal.add_acceptances(
                [
                    Acceptance(
                        id=new_id(),
                        user_id=user_id,
                        kind=i.kind,
                        version=i.version,
                        accepted_at=now,
                        ip=ip,
                        user_agent=user_agent,
                        app_scope=i.app_scope,
                        guardian_attested=guardian_attested
                        and i.app_scope != GLOBAL_APP,
                    )
                    for i in dict.fromkeys(items)
                ]
            )
            await uow.commit()
        return await pending_for(self._uow_factory, user_id, app)
