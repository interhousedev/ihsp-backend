"""In-memory unit of work of the legal module."""

import copy
from collections.abc import Callable, Collection, Sequence
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.legal.domain.models import (
    Acceptance,
    DocKey,
    DocumentStatus,
    LegalDocument,
)
from app.shared.notifications import AuditDraft


class FakeLegalStore:
    """The "database": documents, acceptances and committed audits."""

    def __init__(self) -> None:
        """Start empty."""
        self.documents: list[LegalDocument] = []
        self.acceptances: list[Acceptance] = []
        self.audits: list[AuditDraft] = []
        self.commits = 0


class FakeLegalRepository:
    """Documents and acceptances of a FakeLegalStore."""

    def __init__(self, store: FakeLegalStore) -> None:
        """Bind to the store."""
        self.store = store

    async def lock_kind(self, kind: str, app_scope: str) -> None:
        """Nothing to serialize in memory."""

    async def list_documents(self) -> list[LegalDocument]:
        """Every version, by scope, kind then newest first."""
        docs = sorted(
            self.store.documents, key=lambda d: (d.app_scope, d.kind, -d.version)
        )
        return [copy.deepcopy(d) for d in docs]

    async def list_current(
        self, app_scopes: Collection[str] | None = None
    ) -> list[LegalDocument]:
        """The newest published version of each (kind, scope)."""
        newest: dict[DocKey, LegalDocument] = {}
        for doc in self.store.documents:
            key = (doc.kind, doc.app_scope)
            if app_scopes is not None and doc.app_scope not in app_scopes:
                continue
            if doc.status is DocumentStatus.PUBLISHED and (
                key not in newest or doc.version > newest[key].version
            ):
                newest[key] = doc
        return [copy.deepcopy(d) for d in newest.values()]

    async def get_current(self, kind: str, app_scope: str) -> LegalDocument | None:
        """The newest published version of the kind in the scope."""
        found = await self.list_current([app_scope])
        return next((d for d in found if d.kind == kind), None)

    async def get_draft(self, kind: str, app_scope: str) -> LegalDocument | None:
        """The draft of the kind in the scope."""
        for doc in self.store.documents:
            if (
                doc.kind == kind
                and doc.app_scope == app_scope
                and doc.status is DocumentStatus.DRAFT
            ):
                return copy.deepcopy(doc)
        return None

    async def next_version(self, kind: str, app_scope: str) -> int:
        """One after the newest version."""
        versions = [
            d.version
            for d in self.store.documents
            if d.kind == kind and d.app_scope == app_scope
        ]
        return max(versions, default=0) + 1

    async def add(self, document: LegalDocument) -> None:
        """Insert a document."""
        self.store.documents.append(copy.deepcopy(document))

    async def save(self, document: LegalDocument) -> None:
        """Replace the stored document with the same id."""
        docs = self.store.documents
        for i, doc in enumerate(docs):
            if doc.id == document.id:
                docs[i] = copy.deepcopy(document)

    async def accepted_versions(self, user_id: UUID) -> dict[DocKey, set[int]]:
        """Versions the user accepted, by (kind, scope)."""
        found: dict[DocKey, set[int]] = {}
        for a in self.store.acceptances:
            if a.user_id == user_id:
                found.setdefault((a.kind, a.app_scope), set()).add(a.version)
        return found

    async def add_acceptances(self, acceptances: Sequence[Acceptance]) -> None:
        """Insert acceptances, skipping ones already given."""
        for a in acceptances:
            if not any(
                x.user_id == a.user_id
                and x.kind == a.kind
                and x.app_scope == a.app_scope
                and x.version == a.version
                for x in self.store.acceptances
            ):
                self.store.acceptances.append(a)

    async def count_acceptances(self, current: dict[DocKey, int]) -> dict[DocKey, int]:
        """Distinct users per current version."""
        return {
            (kind, scope): len(
                {
                    a.user_id
                    for a in self.store.acceptances
                    if a.kind == kind and a.app_scope == scope and a.version == version
                }
            )
            for (kind, scope), version in current.items()
        }

    async def delete_acceptances(self, user_id: UUID, app_scope: str) -> int:
        """Remove the user's acceptances of the scope."""
        keep = [
            a
            for a in self.store.acceptances
            if not (a.user_id == user_id and a.app_scope == app_scope)
        ]
        removed = len(self.store.acceptances) - len(keep)
        self.store.acceptances[:] = keep
        return removed


class FakeLegalUnitOfWork:
    """Writes at once; audits are kept until commit."""

    def __init__(self, store: FakeLegalStore) -> None:
        """Bind to the store."""
        self.store = store
        self.legal = FakeLegalRepository(store)
        self._audits: list[AuditDraft] = []

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        self._audits.extend(drafts)

    async def __aenter__(self) -> Self:
        """Open."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Drop uncommitted audits."""
        self._audits = []

    async def commit(self) -> None:
        """Publish the audits and count."""
        self.store.audits.extend(self._audits)
        self._audits = []
        self.store.commits += 1


def fake_uow_factory(store: FakeLegalStore) -> Callable[[], FakeLegalUnitOfWork]:
    """A factory of units of work over the store."""
    return lambda: FakeLegalUnitOfWork(store)
