"""`NotebooksQueries`: read access to notebooks for other modules.

A student reads their own notebooks; course staff read the workspace of their course
(the same access check as the HTTP routes: strangers see nothing).
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.notebooks.application.access import (
    load_artifact,
    load_notebook,
    load_source,
)
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.domain.entities import Notebook, Passage, Source
from app.modules.notebooks.domain.enums import ArtifactStatus
from app.modules.notebooks.domain.errors import (
    NotebookNotFoundError,
    SourceNotReadyError,
)
from app.modules.notebooks.domain.text_pages import split_pages
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.base_error import NotFoundError
from app.shared.contracts.embeddings import EmbeddingIndex, QueryVector

SEARCH_MAX = 20
PASSAGE_CHARS = 600
LIST_MAX = 50
_PASSAGE_BATCH = 500


class SourcePageNotFoundError(NotFoundError):
    """The page number is outside the source's text."""

    code = "notebooks/page-not-found"
    message_key = "notebooks-not-found"


def _day(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def _readable(
    uow: NotebooksUnitOfWork, user_id: UUID, notebook_id: UUID
) -> Notebook | None:
    """The live notebook if the user may read it (their own, or their course's)."""
    try:
        return await load_notebook(uow, user_id, notebook_id, write=False)
    except NotebookNotFoundError:
        return None


async def _source_text(uow: NotebooksUnitOfWork, source: Source) -> str:
    """The text of a source: its passages joined by a blank line."""
    parts: list[str] = []
    after = 0
    while True:
        batch: list[Passage] = await uow.passages.list_for_source(
            source.id, after_seq=after, limit=_PASSAGE_BATCH
        )
        parts.extend(p.text for p in batch)
        if len(batch) < _PASSAGE_BATCH:
            return "\n\n".join(parts)
        after = batch[-1].seq


class NotebooksQueriesImpl:
    """Implements `app.shared.contracts.notebooks.NotebooksQueries`."""

    def __init__(
        self,
        uow_factory: UowFactory,
        quota: QuotaService,
        embeddings: EmbeddingIndex | None = None,
    ) -> None:
        """Store the unit of work factory and the quota service.

        `embeddings` makes `search` hybrid (words and meaning); None keeps it lexical.
        """
        self.uow_factory = uow_factory
        self.quota = quota
        self.embeddings = embeddings

    async def list_notebooks(
        self, user_id: UUID, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return ``{id, title, emoji, source_count, last_opened_at}``, newest first."""
        async with self.uow_factory() as uow:
            rows = await uow.notebooks.list_for_owner(
                user_id, query=None, after=None, limit=max(1, min(limit, LIST_MAX))
            )
        return [
            {
                "id": str(n.id),
                "title": n.title,
                "emoji": n.emoji,
                "source_count": n.source_count,
                "last_opened_at": _day(n.last_opened_at),
            }
            for n in rows
        ]

    async def get_notebook(
        self, user_id: UUID, notebook_id: UUID
    ) -> dict[str, Any] | None:
        """Return title, summary, key topics and the sources; None if not the user's."""
        async with self.uow_factory() as uow:
            notebook = await _readable(uow, user_id, notebook_id)
            if notebook is None:
                return None
            sources = await uow.sources.list_for_notebook(notebook_id)
        summary = notebook.summary
        return {
            "id": str(notebook.id),
            "title": notebook.title,
            "emoji": notebook.emoji,
            "summary": summary.summary if summary else None,
            "key_topics": list(summary.key_topics) if summary else [],
            "source_count": notebook.source_count,
            "sources": [
                {
                    "id": str(s.id),
                    "title": s.title,
                    "kind": s.kind.value,
                    "status": s.status.value,
                    "words": s.word_count,
                    "selected": s.selected,
                }
                for s in sources
            ],
        }

    async def search(
        self, user_id: UUID, notebook_id: UUID, query: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Return passages ``{source_id, source_title, seq, page, text}`` by rank."""
        async with self.uow_factory() as uow:
            if await _readable(uow, user_id, notebook_id) is None:
                return []
            usable = [
                s for s in await uow.sources.list_for_notebook(notebook_id) if s.usable
            ]
            if not usable:
                return []
            found = await uow.passages.search(
                notebook_id,
                [s.id for s in usable],
                query,
                max(1, min(limit, SEARCH_MAX)),
                query_vector=await self._vector(query),
            )
        titles = {s.id: s.title for s in usable}
        return [
            {
                "source_id": str(p.source_id),
                "source_title": titles.get(p.source_id, ""),
                "seq": p.seq,
                "page": p.page,
                "text": p.text[:PASSAGE_CHARS],
            }
            for p in found
        ]

    async def _vector(self, query: str) -> QueryVector | None:
        """The vector of the query, None when it cannot be had in time."""
        if self.embeddings is None:
            return None
        return await self.embeddings.embed_query(query)

    async def read_source_page(
        self, user_id: UUID, notebook_id: UUID, source_id: UUID, page: int
    ) -> dict[str, Any]:
        """Return one 8 KB page of a source's text ``{page, pages, text, ...}``."""
        async with self.uow_factory() as uow:
            try:
                source = await load_source(
                    uow, user_id, notebook_id, source_id, write=False
                )
            except NotebookNotFoundError as exc:
                raise NotebookNotFoundError(
                    support_details="notebook or source not found"
                ) from exc
            if not source.usable:
                raise SourceNotReadyError(support_details="the source is not ready")
            text = await _source_text(uow, source)
        pages = split_pages(text)
        if page < 1 or page > len(pages):
            raise SourcePageNotFoundError(
                params={"page": page, "pages": len(pages)},
                support_details=f"page {page} does not exist, there are {len(pages)}",
            )
        return {
            "source_id": str(source.id),
            "title": source.title,
            "page": page,
            "pages": len(pages),
            "text": pages[page - 1],
        }

    async def list_artifacts(
        self, user_id: UUID, notebook_id: UUID
    ) -> list[dict[str, Any]]:
        """Return ``{id, kind, title, status}`` of the notebook's outputs."""
        async with self.uow_factory() as uow:
            try:
                await load_notebook(uow, user_id, notebook_id, write=False)
            except NotebookNotFoundError:
                return []
            rows = await uow.artifacts.list_for_notebook(
                notebook_id, kind=None, status=None
            )
        return [
            {
                "id": str(a.id),
                "kind": a.kind.value,
                "title": a.title,
                "status": a.status.value,
            }
            for a in rows
        ]

    async def used_by_files(
        self, file_ids: Sequence[UUID]
    ) -> dict[UUID, list[tuple[str, UUID, str]]]:
        """Return ``("notebook", notebook_id, title)`` per file, for the warning."""
        if not file_ids:
            return {}
        keys = {f"file:{file_id}": file_id for file_id in file_ids}
        used: dict[UUID, list[tuple[str, UUID, str]]] = {}
        async with self.uow_factory() as uow:
            sources = await uow.sources.list_by_ref_keys(list(keys))
            books: dict[UUID, Notebook | None] = {}
            for source in sources:
                file_id = keys.get(source.ref_key or "")
                if file_id is None:
                    continue
                if source.notebook_id not in books:
                    books[source.notebook_id] = await uow.notebooks.get(
                        source.notebook_id
                    )
                book = books[source.notebook_id]
                if book is None or book.is_deleted:
                    continue
                entry = ("notebook", book.id, book.title)
                places = used.setdefault(file_id, [])
                if entry not in places:
                    places.append(entry)
        return used

    async def usage(self, user_id: UUID) -> dict[str, Any]:
        """Return the quota counters ``{"artifacts": {"used", "limit"}, ...}``."""
        snapshot = await self.quota.snapshot(user_id)
        return {
            name: {
                "used": part.used,
                "limit": part.limit,
                "resets_at": part.resets_at.isoformat(),
            }
            for name, part in snapshot.items()
        }

    async def course_workspace(
        self, user_id: UUID, course_id: UUID
    ) -> dict[str, Any] | None:
        """Return ``{id, title, course_id, can_write}`` of the course's workspace.

        None when the course has no workspace yet or the user may not read it.
        """
        async with self.uow_factory() as uow:
            access = await uow.course_gate.access(user_id, course_id)
            if access is None or not access.can_read:
                return None
            notebook = await uow.notebooks.get_by_course(course_id)
        if notebook is None:
            return None
        return {
            "id": str(notebook.id),
            "title": notebook.title,
            "course_id": str(course_id),
            "can_write": access.can_write,
        }

    async def get_artifact_content(
        self, user_id: UUID, notebook_id: UUID, artifact_id: UUID
    ) -> dict[str, Any] | None:
        """Return ``{id, kind, title, status, content}`` of a ready output.

        None when the output does not exist, is not ready or is not the user's to
        read.
        """
        async with self.uow_factory() as uow:
            try:
                artifact = await load_artifact(
                    uow, user_id, notebook_id, artifact_id, write=False
                )
            except NotebookNotFoundError:
                return None
        if artifact.status is not ArtifactStatus.READY or artifact.content is None:
            return None
        return {
            "id": str(artifact.id),
            "kind": artifact.kind.value,
            "title": artifact.title,
            "status": artifact.status.value,
            "content": artifact.content,
        }
