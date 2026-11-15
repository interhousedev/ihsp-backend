"""Reading legal documents: public, pending for a user, and for administrators."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.modules.legal.domain.errors import (
    LegalAcceptanceRequiredError,
    LegalNotFoundError,
)
from app.modules.legal.domain.models import LegalDocument
from app.modules.legal.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class PendingItem:
    """A current document the user has not accepted."""

    document: LegalDocument
    previously_accepted_version: int | None


@dataclass(frozen=True, slots=True)
class AcceptanceCount:
    """How many users accepted the current version of a kind."""

    kind: str
    version: int
    accepted_count: int


async def pending_for(uow_factory: UowFactory, user_id: UUID) -> list[PendingItem]:
    """Current documents whose current version the user has not accepted."""
    async with uow_factory() as uow:
        current = await uow.legal.list_current()
        accepted = await uow.legal.accepted_versions(user_id)
    pending = []
    for document in current:
        seen = accepted.get(document.kind, set())
        if document.version not in seen:
            pending.append(PendingItem(document, max(seen) if seen else None))
    return pending


class ListCurrentDocuments:
    """The current published version of every kind (public)."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self) -> list[LegalDocument]:
        """Return the documents, one per published kind."""
        async with self._uow_factory() as uow:
            return await uow.legal.list_current()


class GetCurrentDocument:
    """The current published version of one kind (public)."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, kind: str) -> LegalDocument:
        """Return the document.

        Raises:
            LegalNotFoundError: The kind has no published version.
        """
        async with self._uow_factory() as uow:
            document = await uow.legal.get_current(kind)
        if document is None:
            raise LegalNotFoundError(params={"kind": kind})
        return document


class ListPending:
    """What the signed-in user still has to accept."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, user_id: UUID) -> list[PendingItem]:
        """Return the pending documents; empty when nothing is published."""
        return await pending_for(self._uow_factory, user_id)


CONSENT_CACHE_SECONDS = 30.0
CONSENT_CACHE_MAX_USERS = 50_000


class RequireConsent:
    """Gate: refuses a user who has not accepted every current document.

    The gate runs on every authenticated request, so a user who passed it is
    remembered in this process for ``CONSENT_CACHE_SECONDS``. Only a pass is cached:
    accepting takes effect at once. Publishing in this process clears the cache
    (``forget_all``); another process sees a new version within the TTL.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        ttl_seconds: float = CONSENT_CACHE_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._ttl = ttl_seconds
        self._monotonic = monotonic
        self._passed: dict[UUID, float] = {}

    def forget_all(self) -> None:
        """Drop every cached pass (a new version was published)."""
        self._passed.clear()

    async def execute(self, user_id: UUID) -> None:
        """Raise LegalAcceptanceRequiredError while any document is pending."""
        now = self._monotonic()
        until = self._passed.get(user_id)
        if until is not None and until > now:
            return
        pending = await pending_for(self._uow_factory, user_id)
        if pending:
            self._passed.pop(user_id, None)
            kinds = ", ".join(item.document.kind for item in pending)
            raise LegalAcceptanceRequiredError(params={"kinds": kinds})
        if len(self._passed) >= CONSENT_CACHE_MAX_USERS:
            self._passed = {u: t for u, t in self._passed.items() if t > now}
            if len(self._passed) >= CONSENT_CACHE_MAX_USERS:
                self._passed.clear()
        self._passed[user_id] = now + self._ttl


class ListAllDocuments:
    """Every version of every kind (administrators)."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self) -> list[LegalDocument]:
        """Return all versions, by kind then newest first."""
        async with self._uow_factory() as uow:
            return await uow.legal.list_documents()


class CountAcceptances:
    """Acceptances of the current version of each published kind."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self) -> list[AcceptanceCount]:
        """Return a count per published kind."""
        async with self._uow_factory() as uow:
            current = {d.kind: d.version for d in await uow.legal.list_current()}
            counts = await uow.legal.count_acceptances(current)
        return [AcceptanceCount(k, current[k], counts.get(k, 0)) for k in current]
