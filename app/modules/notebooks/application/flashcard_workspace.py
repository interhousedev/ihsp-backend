"""Use case: prepare the hidden notebook behind "Add new questions with AI" (NB-FC)."""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook, load_source
from app.modules.notebooks.application.add_sources import AddSources
from app.modules.notebooks.application.artifact_engine import ACTIVE, mark_canceled
from app.modules.notebooks.application.copy_notebook import UNFINISHED, cloned_source
from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.domain.entities import Artifact, Notebook, Source
from app.modules.notebooks.domain.enums import NotebookOrigin, SourceStatus
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    NotebookNotFoundError,
    SourceDuplicateError,
    SourceLimitError,
    SourceUnsupportedError,
)
from app.modules.notebooks.domain.source_input import FileInput
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.limits import LimitsProvider
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker

WORKSPACE_TITLE = "Flash cards"


@dataclass(frozen=True, slots=True)
class FlashcardWorkspace:
    """The hidden notebook and the sources of this request."""

    notebook: Notebook
    sources: list[Source]


class OpenFlashcardWorkspace:
    """Puts the chosen sources into the student's one hidden notebook.

    Studio works on one notebook, while a set may draw on several notebooks and on My
    files. The notebook holds only the latest request: an older selection and its
    outputs are dropped. Notebook sources are copied (nothing is read again), files go
    through `AddSources`, and the client then calls the usual Studio routes.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        settings: Settings,
        rate_limiter: RateLimiter,
        kicker: TaskKicker,
        add_sources: AddSources,
        quota: QuotaService,
        limits: LimitsProvider,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.settings = settings
        self.rate_limiter = rate_limiter
        self.kicker = kicker
        self.add_sources = add_sources
        self.quota = quota
        self.limits = limits

    async def execute(
        self,
        actor: Actor,
        notebook_sources: Sequence[tuple[UUID, UUID]],
        file_ids: Sequence[UUID],
    ) -> FlashcardWorkspace:
        """Replace the workspace's sources with the chosen ones.

        Raises:
            InvalidOptionsError: No items, or more than `add_batch_max`.
            NotebookNotFoundError: A notebook or source that is not the caller's.
            SourceForbiddenError: A file that is not the caller's.
            SourceUnsupportedError: A source that failed to be read.
            SourceLimitError: The chosen texts are too long together.
        """
        pairs = list(dict.fromkeys(notebook_sources))
        files = list(dict.fromkeys(file_ids))
        batch_max = self.settings.notebooks.add_batch_max
        if not 1 <= len(pairs) + len(files) <= batch_max:
            raise InvalidOptionsError(params={"field": "items", "max": batch_max})
        canceled: list[Artifact] = []
        async with self.uow_factory() as uow:
            originals = [
                await self._original(uow, actor, notebook_id, source_id)
                for notebook_id, source_id in pairs
            ]
            await self._check_size(originals)
            await self._count(actor, len(originals))
            notebook = await self._notebook(uow, actor)
            canceled = await self._clear(uow, notebook)
            await self._copy(uow, notebook, originals)
            await uow.commit()
        for artifact in canceled:
            await self.quota.pool(False).finished(artifact.charged_to, artifact.id)
        await self._add_files(actor, notebook.id, files)
        async with self.uow_factory() as uow:
            stored = await uow.notebooks.get(notebook.id)
            sources = await uow.sources.list_for_notebook(notebook.id)
        return FlashcardWorkspace(notebook=stored or notebook, sources=sources)

    async def _original(
        self, uow: NotebooksUnitOfWork, actor: Actor, notebook_id: UUID, source_id: UUID
    ) -> Source:
        """A source of the caller's own notebook; shared workspaces do not count."""
        notebook = await load_notebook(uow, actor.user_id, notebook_id, write=False)
        if (
            notebook.owner_id != actor.user_id
            or notebook.is_course_workspace
            or notebook.is_flashcard_workspace
        ):
            raise NotebookNotFoundError()
        source = await load_source(
            uow, actor.user_id, notebook_id, source_id, write=False
        )
        if not source.usable and source.status not in UNFINISHED:
            raise SourceUnsupportedError(
                params={"hint": "kind", "kind": source.kind.value}
            )
        return source

    async def _check_size(self, originals: Sequence[Source]) -> None:
        cap = self.settings.notebooks.notebook_max_chars
        if sum(source.char_count for source in originals) > cap:
            raise SourceLimitError(params={"limit": cap, "what": "characters"})

    async def _count(self, actor: Actor, copies: int) -> None:
        """Copies count against the same hourly limit as added sources."""
        limits = await self.limits.current()
        for _ in range(copies):
            await self.rate_limiter.hit(
                f"nb-src:{actor.user_id}",
                limit=limits.nb_source_adds_per_hour,
                window_seconds=3600,
            )

    async def _notebook(self, uow: NotebooksUnitOfWork, actor: Actor) -> Notebook:
        """Get or create the owner's hidden notebook and lock it."""
        found = await self._find(uow, actor)
        if found is None:
            now = self.clock.now()
            created = Notebook(
                id=new_id(),
                owner_id=actor.user_id,
                title=WORKSPACE_TITLE,
                title_auto=False,
                emoji_auto=False,
                created_at=now,
                updated_at=now,
                origin=NotebookOrigin.FLASHCARDS,
            )
            if await uow.notebooks.add_flashcard_workspace(created):
                return created
            found = await self._find(uow, actor)  # a parallel request made it first
            if found is None:
                raise NotebookNotFoundError(support_details="flash card race lost")
        return await load_notebook(uow, actor.user_id, found.id, for_update=True)

    @staticmethod
    async def _find(uow: NotebooksUnitOfWork, actor: Actor) -> Notebook | None:
        rows = await uow.notebooks.list_for_owner(
            actor.user_id,
            query=None,
            after=None,
            limit=1,
            origin=NotebookOrigin.FLASHCARDS,
        )
        return rows[0] if rows else None

    async def _clear(
        self, uow: NotebooksUnitOfWork, notebook: Notebook
    ) -> list[Artifact]:
        """Drop the previous request; return the outputs that were still running."""
        now = self.clock.now()
        running: list[Artifact] = []
        rows = await uow.artifacts.list_for_notebook(
            notebook.id, kind=None, status=None
        )
        for row in rows:
            artifact = await uow.artifacts.get_for_update(row.id)
            if artifact is None:
                continue
            if artifact.status in ACTIVE:
                mark_canceled(artifact, now)
                running.append(artifact)
            artifact.deleted_at = now
            artifact.updated_at = now
            await uow.artifacts.save(artifact)
        for source in await uow.sources.list_for_notebook(notebook.id):
            await uow.sources.delete(source.id)
        return running

    async def _copy(
        self,
        uow: NotebooksUnitOfWork,
        notebook: Notebook,
        originals: Sequence[Source],
    ) -> None:
        """Store the copies (one per text) and read the unfinished ones afterwards."""
        now = self.clock.now()
        keys: set[str] = set()
        position = 0
        for original in originals:
            key = original.ref_key
            if key is not None and key in keys:
                continue
            if key is not None:
                keys.add(key)
            clone = cloned_source(original, notebook, now)
            clone.position = position
            clone.selected = True
            position += 1
            await uow.sources.add(clone)
            if clone.status is SourceStatus.PENDING:
                uow.after_commit(
                    partial(
                        self.kicker.kick,
                        "notebooks.process_source",
                        source_id=str(clone.id),
                    )
                )
        await sources_changed(uow, notebook, now)

    async def _add_files(
        self, actor: Actor, notebook_id: UUID, files: Sequence[UUID]
    ) -> None:
        """Add the files; the first real refusal fails the request."""
        if not files:
            return
        items = [FileInput(file_id=file_id) for file_id in files]
        result = await self.add_sources.execute(actor, notebook_id, items)
        for rejected in result.rejected:
            if not isinstance(rejected.error, SourceDuplicateError):
                raise rejected.error
