"""Use case: rename a source, tick its checkbox or edit its text (NB-4)."""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook, load_source
from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import SourceStatus
from app.modules.notebooks.domain.errors import (
    InvalidOptionsError,
    SourceLimitError,
    SourceNotReadyError,
    SourceTooLargeError,
)
from app.modules.notebooks.domain.limits import SOURCE_TITLE_MAX_CHARS
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

ALLOWED_FIELDS = frozenset({"title", "selected", "body_md"})
UNFINISHED = (SourceStatus.PENDING, SourceStatus.PROCESSING)


def _invalid(field: str) -> InvalidOptionsError:
    return InvalidOptionsError(params={"field": field})


def _checked_title(value: Any) -> str:
    """A one-line title of 1 to 255 characters."""
    title = " ".join(value.split()) if isinstance(value, str) else ""
    if not title or len(title) > SOURCE_TITLE_MAX_CHARS:
        raise _invalid("title")
    return title


def _checked_flag(value: Any) -> bool:
    if not isinstance(value, bool):
        raise _invalid("selected")
    return value


def _checked_body(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid("body_md")
    return value


@dataclass(frozen=True, slots=True)
class _Changes:
    """The validated fields of a request (None: not given)."""

    title: str | None = None
    selected: bool | None = None
    body: str | None = None


def _parse(changes: Mapping[str, Any]) -> _Changes:
    """Validate the request body before anything is read from the database."""
    unknown = sorted(set(changes) - ALLOWED_FIELDS)
    if unknown:
        raise _invalid(unknown[0])
    return _Changes(
        title=_checked_title(changes["title"]) if "title" in changes else None,
        selected=_checked_flag(changes["selected"]) if "selected" in changes else None,
        body=_checked_body(changes["body_md"]) if "body_md" in changes else None,
    )


class UpdateSource:
    """Applies the allowed changes (`title`, `selected`, `body_md`) to a source."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        settings: Settings,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.settings = settings
        self.kicker = kicker

    async def execute(
        self,
        actor: Actor,
        notebook_id: UUID,
        source_id: UUID,
        changes: Mapping[str, Any],
    ) -> Source:
        """Apply the changes and return the source.

        A new `body_md` (pasted text and notes without citations) puts the source
        back to `pending`: its passages are rebuilt and the guide is written again.

        Raises:
            NotebookNotFoundError: Notebook or source is not the caller's.
            InvalidOptionsError: An unknown or invalid field, or a body for a source
                that cannot be edited.
            SourceNotReadyError: The body of a source that is still processing.
            SourceTooLargeError: The new text is over the per-source cap.
            SourceLimitError: The new text does not fit into the notebook.
        """
        parsed = _parse(changes)
        now = self.clock.now()
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, for_update=True
            )
            source = await load_source(
                uow, actor.user_id, notebook_id, source_id, for_update=True
            )
            recount = await self._apply(uow, notebook, source, parsed)
            source.updated_at = now
            await uow.sources.save(source)
            if recount:
                await sources_changed(uow, notebook, now)
            await uow.commit()
        return source

    async def _apply(
        self,
        uow: NotebooksUnitOfWork,
        notebook: Notebook,
        source: Source,
        parsed: _Changes,
    ) -> bool:
        """Change the entity; True when the notebook's counters must be refreshed."""
        recount = False
        if parsed.title is not None:
            source.title = parsed.title
        if parsed.selected is not None and parsed.selected != source.selected:
            source.selected = parsed.selected
            recount = True
        if parsed.body is not None and parsed.body != source.body_md:
            await self._edit_body(uow, notebook, source, parsed.body)
            recount = True
        return recount

    async def _edit_body(
        self, uow: NotebooksUnitOfWork, notebook: Notebook, source: Source, body: str
    ) -> None:
        """Store the new text and queue the re-chunking after the commit."""
        if not source.editable:
            raise _invalid("body_md")
        if source.status in UNFINISHED:
            raise SourceNotReadyError()
        limits = self.settings.notebooks
        if len(body) > limits.source_max_chars:
            raise SourceTooLargeError(params={"limit": limits.source_max_chars})
        total = await uow.sources.total_chars(notebook.id)
        kept = source.char_count if source.usable else 0
        if total - kept + len(body) > limits.notebook_max_chars:
            raise SourceLimitError(
                params={"limit": limits.notebook_max_chars, "what": "characters"}
            )
        source.body_md = body
        source.status = SourceStatus.PENDING
        source.failure = None
        uow.after_commit(
            partial(
                self.kicker.kick, "notebooks.process_source", source_id=str(source.id)
            )
        )
