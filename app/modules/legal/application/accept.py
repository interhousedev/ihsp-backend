"""A signed-in user accepts the current versions."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.legal.application.queries import PendingItem, pending_for
from app.modules.legal.domain.errors import LegalStaleVersionError
from app.modules.legal.domain.models import Acceptance
from app.modules.legal.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.legal import LegalItem
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
    ) -> list[PendingItem]:
        """Accept the items and return what is still pending.

        Raises:
            LegalStaleVersionError: An item is not the current version of its kind
                (nothing is recorded).
        """
        now = self._clock.now()
        async with self._uow_factory() as uow:
            current = {d.kind: d.version for d in await uow.legal.list_current()}
            for item in items:
                if current.get(item.kind) != item.version:
                    raise LegalStaleVersionError(
                        params={
                            "kind": item.kind,
                            "current": current.get(item.kind) or 0,
                        }
                    )
            await uow.legal.add_acceptances(
                [
                    Acceptance(
                        new_id(), user_id, i.kind, i.version, now, ip, user_agent
                    )
                    for i in dict.fromkeys(items)
                ]
            )
            await uow.commit()
        return await pending_for(self._uow_factory, user_id)
