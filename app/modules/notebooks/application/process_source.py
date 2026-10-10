"""Job `notebooks.process_source`: read, chunk and store a source (§ 3.2.2)."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from uuid import UUID

from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.readers.base import SourceText
from app.modules.notebooks.application.readers.file_reader import file_id_of
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.application.readers.unavailable import mark_unavailable
from app.modules.notebooks.domain.chunker import ChunkResult, chunk_source
from app.modules.notebooks.domain.entities import Document, Notebook, Source
from app.modules.notebooks.domain.enums import (
    GuideStatus,
    SourceFailure,
    SourceKind,
    SourceStatus,
)
from app.modules.notebooks.domain.errors import (
    SourceReadError,
    SourceUnavailableError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.library_sources import library_key
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.settings import Settings
from app.shared.clock import Clock
from app.shared.features import Feature, is_enabled
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

STARTABLE = (SourceStatus.PENDING, SourceStatus.PROCESSING, SourceStatus.STALE)
RAW_TEXT_FACTOR = 2  # normalising only shrinks a text, so 2x the cap is hopeless


@dataclass(frozen=True, slots=True)
class Withdrawn:
    """The upstream object cannot be used now (`unavailable`, a sync may revive it)."""

    failure: SourceFailure


class ProcessSource:
    """Turns a pending source into passages; safe to run twice (taskiq may retry)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        settings: Settings,
        readers: SourceReaders,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.settings = settings
        self.readers = readers
        self.kicker = kicker

    async def execute(self, source_id: UUID) -> None:
        """Run the pipeline for one source.

        Reader errors end in `failed(<code>)` for good. Any other exception
        propagates: the task is retried and the stuck-source sweep re-kicks it.
        """
        source = await self._claim(source_id)
        if source is None:
            return
        shared = await self._known_document(source)
        if shared is not None:
            await self._store_shared(source, shared)
            return
        prepared = await self._prepare(source)
        if isinstance(prepared, Withdrawn):
            await self._withdraw(source, prepared.failure)
            return
        if isinstance(prepared, SourceFailure):
            await self._fail(source, prepared)
            return
        await self._store(source, *prepared)

    # - - - Steps - - -

    async def _claim(self, source_id: UUID) -> Source | None:
        """Lock the row, skip sources that are not waiting, mark `processing`."""
        async with self.uow_factory() as uow:
            source = await uow.sources.get_for_update(source_id)
            if source is None or source.status not in STARTABLE:
                return None
            notebook = await uow.notebooks.get(source.notebook_id)
            if notebook is None or notebook.is_deleted:
                return None
            source.status = SourceStatus.PROCESSING
            source.updated_at = self.clock.now()
            await uow.sources.save(source)
            await uow.commit()
        return source

    async def _known_document(self, source: Source) -> Document | None:
        """The document of a file that was read before (by anyone), if any.

        Files never change, so the text of a file id is read and chunked once for the
        whole school: 30 students with the same lesson file cost one reading.
        """
        alias = alias_of(source)
        if alias is None:
            return None
        if source.id in await self.readers.unavailable_files([source]):
            return None  # FILE-6: a deleted file's text must not come back
        if source.id in await self.readers.unavailable_library([source]):
            return None  # LIB-10: a held book's text is not handed to a new source
        async with self.uow_factory() as uow:
            return await uow.documents.find_by_alias(alias)

    async def _prepare(
        self, source: Source
    ) -> tuple[SourceText, ChunkResult] | SourceFailure | Withdrawn:
        """Read and chunk the text, or say why the source cannot be used.

        The reader runs with no transaction open (it may take seconds).
        """
        try:
            text = await self.readers.for_kind(source.kind).read(source)
        except SourceUnavailableError as error:
            return Withdrawn(_failure_of(error.failure))
        except SourceReadError as error:
            return _failure_of(error.failure)
        except SourceUnsupportedError:
            return SourceFailure.UNSUPPORTED_TYPE
        cap = self.settings.notebooks.source_max_chars
        if len(text.text) > cap * RAW_TEXT_FACTOR:
            return SourceFailure.TOO_LARGE
        chunked = await asyncio.to_thread(
            chunk_source,
            text.text,
            page_starts=text.page_starts,
            unit_starts=text.unit_starts,
        )
        return self._check(chunked) or (text, chunked)

    def _check(self, chunked: ChunkResult) -> SourceFailure | None:
        """Empty and oversized texts end the pipeline."""
        if not chunked.text.strip() or not chunked.passages:
            return SourceFailure.NO_TEXT
        if chunked.char_count > self.settings.notebooks.source_max_chars:
            return SourceFailure.TOO_LARGE
        return None

    async def _fail(self, source: Source, failure: SourceFailure) -> None:
        """Store the failure (final: no retry)."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            locked = await self._lock(uow, source)
            if locked is None:
                return
            notebook, current = locked
            current.status = SourceStatus.FAILED
            current.failure = failure
            current.updated_at = now
            await uow.sources.save(current)
            await sources_changed(uow, notebook, now)
            await uow.commit()
        log.info(
            "notebooks_source_failed",
            source_id=str(source.id),
            kind=source.kind.value,
            failure=failure.value,
        )

    async def _withdraw(self, source: Source, failure: SourceFailure) -> None:
        """The upstream object cannot be used now: `unavailable` (a sync revives it)."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            locked = await self._lock(uow, source)
            if locked is None:
                return
            notebook, current = locked
            await mark_unavailable(uow, current, now, failure)
            await sources_changed(uow, notebook, now)
            await uow.commit()
        log.info(
            "notebooks_source_unavailable",
            source_id=str(source.id),
            kind=source.kind.value,
            failure=failure.value,
        )

    async def _store(
        self, source: Source, text: SourceText, chunked: ChunkResult
    ) -> None:
        """Keep the text as a shared document (unless unchanged) and mark `ready`."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            locked = await self._lock(uow, source)
            if locked is None:
                return
            notebook, current = locked
            unchanged = (
                current.content_hash == chunked.content_hash
                and current.document_id is not None
            )
            # Before attaching: a live step's alias names the revision that was read.
            current.ref = {**current.ref, **text.ref_update}
            if not unchanged:
                document = await uow.documents.create(
                    chunked.content_hash,
                    chunked.passages,
                    word_count=chunked.word_count,
                    char_count=chunked.char_count,
                    token_estimate=chunked.token_estimate,
                )
                await self._attach(uow, current, document)
                self._kick_embeddings(uow, document)
            current.upstream_version = text.upstream_version
            await self._ready(uow, notebook, current, now, kick_guide=not unchanged)
            await uow.commit()
        log.info(
            "notebooks_source_ready",
            source_id=str(source.id),
            kind=source.kind.value,
            passages=current.passage_count,
            chars=current.char_count,
            unchanged=unchanged,
        )

    async def _store_shared(self, source: Source, document: Document) -> None:
        """Mark a source `ready` on a document that already exists: no reading."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            locked = await self._lock(uow, source)
            if locked is None:
                return
            notebook, current = locked
            await self._attach(uow, current, document)
            if source.kind is SourceKind.LMS_STEP and current.ref.get("revision_id"):
                current.upstream_version = str(current.ref["revision_id"])
            await self._ready(uow, notebook, current, now, kick_guide=True)
            await uow.commit()
        log.info(
            "notebooks_source_shared",
            source_id=str(source.id),
            kind=source.kind.value,
            document_id=str(document.id),
        )

    def _kick_embeddings(self, uow: NotebooksUnitOfWork, document: Document) -> None:
        """Vectors for the new passages, after commit (search by meaning, NB-14).

        The cron backfill would find them too; the kick makes them searchable in
        seconds. Texts that already have a vector are skipped by the job.
        """
        if not is_enabled(self.settings, Feature.VECTOR_SEARCH):
            return
        uow.after_commit(
            partial(
                self.kicker.kick,
                "notebooks.embed_passages",
                document_id=str(document.id),
            )
        )

    @staticmethod
    async def _attach(
        uow: NotebooksUnitOfWork, current: Source, document: Document
    ) -> None:
        """Point the source at the document and copy its counters."""
        current.document_id = document.id
        current.content_hash = document.content_hash
        current.word_count = document.word_count
        current.char_count = document.char_count
        current.token_estimate = document.token_estimate
        current.passage_count = document.passage_count
        current.guide = None
        current.guide_status = GuideStatus.NONE
        alias = alias_of(current)
        if alias is not None:
            await uow.documents.add_aliases([alias], document.id)

    async def _ready(
        self,
        uow: NotebooksUnitOfWork,
        notebook: Notebook,
        current: Source,
        now: datetime,
        *,
        kick_guide: bool,
    ) -> None:
        """Mark the source ready, refresh the notebook, kick its guide."""
        current.text_synced_at = now
        current.status = SourceStatus.READY
        current.failure = None
        current.updated_at = now
        await uow.sources.save(current)
        await sources_changed(uow, notebook, now)
        if kick_guide:
            uow.after_commit(
                partial(
                    self.kicker.kick,
                    "notebooks.build_source_guide",
                    source_id=str(current.id),
                )
            )

    async def _lock(
        self, uow: NotebooksUnitOfWork, source: Source
    ) -> tuple[Notebook, Source] | None:
        """Lock the notebook, then the source (the order of every writer).

        Returns None when the source was deleted, or is no longer being processed
        (another run finished it first).
        """
        notebook = await uow.notebooks.get_for_update(source.notebook_id)
        current = await uow.sources.get_for_update(source.id)
        if (
            notebook is None
            or notebook.is_deleted
            or current is None
            or current.status is not SourceStatus.PROCESSING
        ):
            return None
        return notebook, current


def alias_of(source: Source) -> str | None:
    """The stable identity of a file-backed source's text.

    `file:<file id>` for files and lesson materials, `library:<file id>:<from>:<to>`
    for a book or a chapter (the notes of one student have none: they are personal).
    """
    if source.kind is SourceKind.LIBRARY_NOTES:
        return None
    if source.kind is SourceKind.LMS_STEP:
        return lms_alias(source)
    file_id = file_id_of(source)
    if file_id is None:
        return None
    if source.kind is SourceKind.LIBRARY_ITEM:
        return library_key(
            file_id,
            _page(source, "page_from"),
            _page(source, "page_to"),
        )
    return f"file:{file_id}"


def lms_alias(source: Source) -> str | None:
    """The identity of a live course step (or one of its videos) at its revision.

    Every enrolled student reads the same revision, so it is read and chunked once for
    all course notebooks. Drafts and sources without a known revision have none.
    """
    revision = source.ref.get("revision_id")
    if not revision or source.ref.get("draft"):
        return None
    block_id = source.ref.get("block_id")
    suffix = f":{block_id}" if block_id else ""
    return f"lms:{source.ref.get('step_id')}:{revision}{suffix}"


def _page(source: Source, key: str) -> int | None:
    """A page number of a library source's `ref`."""
    value = source.ref.get(key)
    return None if value is None else int(value)


def _failure_of(code: str) -> SourceFailure:
    """The failure of a reader's code (an unknown code counts as a provider error)."""
    try:
        return SourceFailure(code)
    except ValueError:
        return SourceFailure.PROVIDER_ERROR
