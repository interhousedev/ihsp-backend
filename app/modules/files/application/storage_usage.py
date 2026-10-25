"""How much of the quota the caller has used (WEB-21, FILE-5)."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.modules.files.domain.policy import FilesLimits, expiry_date, scope_for
from app.modules.files.ports.term_resolver import TermResolver
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.files import FileScope


@dataclass(frozen=True, slots=True)
class StorageUsageView:
    """Used bytes, the quota and when this term's files are deleted."""

    used_bytes: int
    quota_bytes: int
    term_id: UUID | None
    expires_on: date | None


class StorageUsage:
    """Quota bar of the My files page."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        terms: TermResolver,
        clock: Clock,
        limits: FilesLimits,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._terms = terms
        self._clock = clock
        self._limits = limits

    async def execute(self, actor: Actor) -> StorageUsageView:
        """Students see the current term; staff see their total."""
        scope = scope_for(actor)
        term_id: UUID | None = None
        expires_on: date | None = None
        if scope == FileScope.STUDENT:
            term_id = await self._terms.current_term_id(local_today(self._clock))
            end = None if term_id is None else await self._terms.term_end(term_id)
            expires_on = None if end is None else expiry_date(end)
        async with self._uow_factory() as uow:
            used = await uow.files.used_bytes(actor.user_id, scope, term_id)
        return StorageUsageView(
            used_bytes=used,
            quota_bytes=self._limits.quota_for(scope) or 0,
            term_id=term_id,
            expires_on=expires_on,
        )
