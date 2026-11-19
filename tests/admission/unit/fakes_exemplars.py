"""In-memory exemplar repository and the unit of work that carries it."""

import dataclasses
from uuid import UUID

from app.modules.admission.domain.exemplars import Exemplar
from tests.admission.unit.fakes import FakeStore, FakeUow


class FakeExemplarRepo:
    """Exemplars kept in a dict."""

    def __init__(self, items: dict[UUID, Exemplar], institutions: set[UUID]) -> None:
        """Share the dict and the known institutions."""
        self.items = items
        self.institutions = institutions

    async def add(self, item: Exemplar) -> None:
        self.items[item.id] = item

    async def institution_exists(self, institution_id: UUID) -> bool:
        return institution_id in self.institutions

    async def get(self, exemplar_id: UUID) -> Exemplar | None:
        return self.items.get(exemplar_id)

    async def search(
        self,
        *,
        status: str | None,
        kind: str | None,
        institution_id: UUID | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Exemplar], int]:
        rows = [
            e
            for e in self.items.values()
            if (status is None or e.status == status)
            and (kind is None or e.kind == kind)
            and (institution_id is None or e.institution_id == institution_id)
            and (query is None or query.lower() in e.title.lower())
        ]
        rows.sort(key=lambda e: e.created_at, reverse=True)
        return rows[offset : offset + limit], len(rows)

    async def published(self) -> list[Exemplar]:
        return [e for e in self.items.values() if e.status == "published"]

    async def find_by_source(self, source_url: str, title: str) -> UUID | None:
        for e in self.items.values():
            if (e.source_url, e.title) == (source_url, title):
                return e.id
        return None

    async def update(self, item: Exemplar, *, expected_lock: int) -> bool:
        current = self.items.get(item.id)
        if current is None or current.lock_version != expected_lock:
            return False
        self.items[item.id] = dataclasses.replace(item, lock_version=expected_lock + 1)
        return True

    async def delete(self, exemplar_id: UUID) -> bool:
        return self.items.pop(exemplar_id, None) is not None


class FakeExemplarStore(FakeStore):
    """The store plus the exemplar library."""

    def __init__(self) -> None:
        """Start with an empty library."""
        super().__init__()
        self.exemplars: dict[UUID, Exemplar] = {}
        self.known_institutions: set[UUID] = set()


class FakeExemplarUow(FakeUow):
    """FakeUow with the exemplar repository."""

    def __init__(self, s: FakeExemplarStore) -> None:
        """Bind the store."""
        super().__init__(s)
        self.exemplars = FakeExemplarRepo(s.exemplars, s.known_institutions)
