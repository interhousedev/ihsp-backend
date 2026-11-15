"""In-memory unit of work of the legal module."""

import copy
from collections.abc import Callable, Sequence
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.legal.domain.models import Acceptance, DocumentStatus, LegalDocument
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

    async def lock_kind(self, kind: str) -> None:
        """Nothing to serialize in memory."""

    async def list_documents(self) -> list[LegalDocument]:
        """Every version, by kind then newest first."""
        docs = sorted(self.store.documents, key=lambda d: (d.kind, -d.version))
        return [copy.deepcopy(d) for d in docs]

    async def list_current(self) -> list[LegalDocument]:
        """The newest published version of each kind."""
        newest: dict[str, LegalDocument] = {}
        for doc in self.store.documents:
            if doc.status is DocumentStatus.PUBLISHED and (
                doc.kind not in newest or doc.version > newest[doc.kind].version
            ):
                newest[doc.kind] = doc
        return [copy.deepcopy(d) for d in newest.values()]

    async def get_current(self, kind: str) -> LegalDocument | None:
        """The newest published version of the kind."""
        return next((d for d in await self.list_current() if d.kind == kind), None)

    async def get_draft(self, kind: str) -> LegalDocument | None:
        """The draft of the kind."""
        for doc in self.store.documents:
            if doc.kind == kind and doc.status is DocumentStatus.DRAFT:
                return copy.deepcopy(doc)
        return None

    async def next_version(self, kind: str) -> int:
        """One after the newest version."""
        versions = [d.version for d in self.store.documents if d.kind == kind]
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

    async def accepted_versions(self, user_id: UUID) -> dict[str, set[int]]:
        """Versions the user accepted, by kind."""
        found: dict[str, set[int]] = {}
        for a in self.store.acceptances:
            if a.user_id == user_id:
                found.setdefault(a.kind, set()).add(a.version)
        return found

    async def add_acceptances(self, acceptances: Sequence[Acceptance]) -> None:
        """Insert acceptances, skipping ones already given."""
        for a in acceptances:
            if not any(
                x.user_id == a.user_id and x.kind == a.kind and x.version == a.version
                for x in self.store.acceptances
            ):
                self.store.acceptances.append(a)

    async def count_acceptances(self, current: dict[str, int]) -> dict[str, int]:
        """Distinct users per current version."""
        return {
            kind: len(
                {
                    a.user_id
                    for a in self.store.acceptances
                    if a.kind == kind and a.version == version
                }
            )
            for kind, version in current.items()
        }


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
