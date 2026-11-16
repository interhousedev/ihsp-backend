"""Reading legal documents: public, pending for a user, and for administrators."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.modules.legal.domain.errors import (
    LegalAcceptanceRequiredError,
    LegalNotFoundError,
)
from app.modules.legal.domain.models import DocKey, DocumentStatus, LegalDocument
from app.modules.legal.ports.unit_of_work import UowFactory
from app.shared.contracts.legal import APP_SCOPES, GLOBAL_APP


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
    app_scope: str = GLOBAL_APP


@dataclass(frozen=True, slots=True)
class KindOverview:
    """One document series: its current version, draft and every version."""

    kind: str
    app_scope: str
    current_version: int | None
    accepted_count: int
    draft: LegalDocument | None
    versions: list[LegalDocument]


@dataclass(frozen=True, slots=True)
class ScopeOverview:
    """The document series of one app scope."""

    app_scope: str
    kinds: list[KindOverview]


async def pending_for(
    uow_factory: UowFactory, user_id: UUID, app: str = GLOBAL_APP
) -> list[PendingItem]:
    """Current global and ``app`` documents the user has not accepted."""
    async with uow_factory() as uow:
        current = await uow.legal.list_current({GLOBAL_APP, app})
        accepted = await uow.legal.accepted_versions(user_id)
    pending = []
    for document in current:
        seen = accepted.get((document.kind, document.app_scope), set())
        if document.version not in seen:
            pending.append(PendingItem(document, max(seen) if seen else None))
    return pending


class ListCurrentDocuments:
    """The current published version of every kind of one scope (public)."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, app_scope: str = GLOBAL_APP) -> list[LegalDocument]:
        """Return the documents of the scope, one per published kind."""
        async with self._uow_factory() as uow:
            return await uow.legal.list_current([app_scope])


class GetCurrentDocument:
    """The current published version of one kind (public)."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, kind: str, app_scope: str = GLOBAL_APP) -> LegalDocument:
        """Return the document.

        Raises:
            LegalNotFoundError: The kind has no published version.
        """
        async with self._uow_factory() as uow:
            document = await uow.legal.get_current(kind, app_scope)
        if document is None:
            raise LegalNotFoundError(params={"kind": kind})
        return document


class ListPending:
    """What the signed-in user still has to accept."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self, user_id: UUID, app: str = GLOBAL_APP) -> list[PendingItem]:
        """Return the pending documents; empty when nothing is published."""
        return await pending_for(self._uow_factory, user_id, app)


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
        self._passed: dict[tuple[UUID, str], float] = {}

    def forget_all(self) -> None:
        """Drop every cached pass (a new version was published)."""
        self._passed.clear()

    async def execute(self, user_id: UUID, app: str = GLOBAL_APP) -> None:
        """Raise LegalAcceptanceRequiredError while any document is pending.

        Pending means the current global documents and those of ``app``.
        """
        now = self._monotonic()
        key = (user_id, app)
        until = self._passed.get(key)
        if until is not None and until > now:
            return
        pending = await pending_for(self._uow_factory, user_id, app)
        if pending:
            self._passed.pop(key, None)
            kinds = ", ".join(item.document.kind for item in pending)
            raise LegalAcceptanceRequiredError(params={"kinds": kinds})
        if len(self._passed) >= CONSENT_CACHE_MAX_USERS:
            self._passed = {k: t for k, t in self._passed.items() if t > now}
            if len(self._passed) >= CONSENT_CACHE_MAX_USERS:
                self._passed.clear()
        self._passed[key] = now + self._ttl


class ListAllDocuments:
    """Every version of every kind (administrators)."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self) -> list[LegalDocument]:
        """Return all versions, by kind then newest first."""
        async with self._uow_factory() as uow:
            return await uow.legal.list_documents()


async def _current_counts(
    uow_factory: UowFactory,
) -> tuple[dict[DocKey, int], dict[DocKey, int]]:
    async with uow_factory() as uow:
        current = {
            (d.kind, d.app_scope): d.version for d in await uow.legal.list_current()
        }
        return current, await uow.legal.count_acceptances(current)


class CountAcceptances:
    """Acceptances of the current version of each published kind and scope."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self) -> list[AcceptanceCount]:
        """Return a count per published (kind, scope)."""
        current, counts = await _current_counts(self._uow_factory)
        return [
            AcceptanceCount(kind, version, counts.get((kind, scope), 0), scope)
            for (kind, scope), version in current.items()
        ]


class ListOverview:
    """Documents grouped by app scope, with versions and acceptance counts."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory

    async def execute(self) -> list[ScopeOverview]:
        """Return the scopes that have documents, global first."""
        async with self._uow_factory() as uow:
            documents = await uow.legal.list_documents()
        current, counts = await _current_counts(self._uow_factory)
        series: dict[DocKey, list[LegalDocument]] = {}
        for document in documents:
            series.setdefault((document.kind, document.app_scope), []).append(document)
        groups: dict[str, list[KindOverview]] = {}
        for (kind, scope), versions in sorted(series.items()):
            groups.setdefault(scope, []).append(
                KindOverview(
                    kind=kind,
                    app_scope=scope,
                    current_version=current.get((kind, scope)),
                    accepted_count=counts.get((kind, scope), 0),
                    draft=next(
                        (v for v in versions if v.status is DocumentStatus.DRAFT),
                        None,
                    ),
                    versions=versions,
                )
            )
        order = {name: i for i, name in enumerate(APP_SCOPES)}
        return [
            ScopeOverview(scope, groups[scope])
            for scope in sorted(groups, key=lambda n: order.get(n, len(order)))
        ]
