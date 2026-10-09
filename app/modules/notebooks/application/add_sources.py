"""Use case: add sources to a notebook, one request for up to 20 items (NB-4)."""

from collections.abc import Sequence
from functools import partial
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.application.source_limits import ensure_capacity
from app.modules.notebooks.application.views import AddSourcesResult, RejectedSource
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import SourceStatus
from app.modules.notebooks.domain.errors import (
    AutoNotebookReadOnlyError,
    InvalidOptionsError,
    SourceDuplicateError,
    SourceForbiddenError,
    SourceLimitError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.source_input import LmsStepInput, SourceInput
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

# What a course workspace takes: the staff's own files and texts, web pages, and the
# draft steps of its course (personal chats, flash card sets and lessons are not).
WORKSPACE_KINDS = frozenset({"file", "text", "note", "url", "lms_step"})


def check_fits(notebook: Notebook, item: SourceInput) -> None:
    """Refuse an item that this kind of notebook cannot hold.

    Raises:
        SourceUnsupportedError: A kind a course workspace does not take.
        SourceForbiddenError: A draft step outside the workspace of its course, or
            a live step in a workspace.
    """
    draft = isinstance(item, LmsStepInput) and item.draft
    if not notebook.is_course_workspace:
        if draft:
            raise SourceForbiddenError()
        return
    if item.kind not in WORKSPACE_KINDS:
        raise SourceUnsupportedError(params={"hint": "workspace", "kind": item.kind})
    if isinstance(item, LmsStepInput) and (
        not item.draft or item.course_id != notebook.course_id
    ):
        raise SourceForbiddenError()


class _Batch:
    """What the accepted items of one request already take up."""

    def __init__(self, *, position: int, chars: int) -> None:
        self.position = position
        self.chars = chars  # usable text of the notebook before the request
        self.new_chars = 0  # text of the accepted items (pasted text and notes)
        self.sources: list[Source] = []
        self.keys: set[str] = set()

    def accept(self, source: Source) -> None:
        """Count a source that passed every check."""
        self.sources.append(source)
        self.new_chars += len(source.body_md or "")
        if source.ref_key is not None:
            self.keys.add(source.ref_key)


class AddSources:
    """Checks every item on its own and stores the accepted ones in one transaction."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        settings: Settings,
        rate_limiter: RateLimiter,
        kicker: TaskKicker,
        readers: SourceReaders,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.settings = settings
        self.rate_limiter = rate_limiter
        self.kicker = kicker
        self.readers = readers

    async def execute(
        self, actor: Actor, notebook_id: UUID, items: Sequence[SourceInput]
    ) -> AddSourcesResult:
        """Add the items; a refused item is reported in `rejected`, the rest are stored.

        Every accepted source starts as `pending` and `selected`; processing is kicked
        after the commit. In a course workspace the rows belong to the workspace (its
        owner), while the rate limit and the files checked are the caller's.

        Raises:
            NotebookNotFoundError: The notebook is not the caller's.
            InvalidOptionsError: No items, or more than `add_batch_max`.
            AutoNotebookReadOnlyError: A subject or lesson notebook only takes notes.
        """
        if not 1 <= len(items) <= self.settings.notebooks.add_batch_max:
            raise InvalidOptionsError(
                params={"field": "items", "max": self.settings.notebooks.add_batch_max}
            )
        result = AddSourcesResult()
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, for_update=True
            )
            if notebook.is_auto and any(item.kind != "note" for item in items):
                raise AutoNotebookReadOnlyError()
            batch = _Batch(
                position=await uow.sources.next_position(notebook.id),
                chars=await uow.sources.total_chars(notebook.id),
            )
            for index, item in enumerate(items):
                try:
                    batch.accept(await self._check(uow, actor, notebook, item, batch))
                except BaseError as error:
                    result.rejected.append(RejectedSource(index, error))
            if batch.sources:
                await self._store(uow, notebook, batch.sources)
                await uow.commit()
        result.items = batch.sources
        log.info(
            "notebooks_sources_added",
            notebook_id=str(notebook_id),
            added=len(batch.sources),
            rejected=len(result.rejected),
        )
        return result

    async def _check(
        self,
        uow: NotebooksUnitOfWork,
        actor: Actor,
        notebook: Notebook,
        item: SourceInput,
        batch: _Batch,
    ) -> Source:
        """Build the source of one item or raise why it was refused."""
        check_fits(notebook, item)
        limits = self.settings.limits
        await self.rate_limiter.hit(
            f"nb-src:{actor.user_id}",
            limit=limits.nb_source_adds_per_hour,
            window_seconds=3600,
        )
        resolved = await self.readers.resolve(actor.user_id, item)
        key = resolved.ref_key
        if key is not None and (
            key in batch.keys or await uow.sources.ref_key_exists(notebook.id, key)
        ):
            raise SourceDuplicateError()
        size = len(resolved.body_md or "")
        await ensure_capacity(
            uow, notebook, size, self.settings, pending=len(batch.sources)
        )
        notebook_cap = self.settings.notebooks.notebook_max_chars
        if batch.chars + batch.new_chars + size > notebook_cap:
            raise SourceLimitError(params={"limit": notebook_cap, "what": "characters"})
        now = self.clock.now()
        return Source(
            id=new_id(),
            notebook_id=notebook.id,
            owner_id=notebook.owner_id,
            kind=resolved.kind,
            title=resolved.title,
            position=batch.position + len(batch.sources),
            created_at=now,
            updated_at=now,
            ref=resolved.ref,
            ref_key=key,
            origin=resolved.origin,
            selected=True,
            status=SourceStatus.PENDING,
            body_md=resolved.body_md,
        )

    async def _store(
        self, uow: NotebooksUnitOfWork, notebook: Notebook, sources: list[Source]
    ) -> None:
        """Insert the accepted sources and kick their processing after the commit."""
        for source in sources:
            await uow.sources.add(source)
            uow.after_commit(
                partial(
                    self.kicker.kick,
                    "notebooks.process_source",
                    source_id=str(source.id),
                )
            )
        await sources_changed(uow, notebook, self.clock.now())
