"""Use case: make a normal, editable copy of a notebook (NB-AUTO)."""

from functools import partial
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.copy_labels import copy_labels
from app.modules.notebooks.application.locale import LocaleResolver
from app.modules.notebooks.application.notebook_state import (
    selection_hash,
    sources_changed,
)
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.enums import (
    GuideStatus,
    NotebookOrigin,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.domain.errors import (
    NotebookLimitError,
    WorkspaceActionError,
)
from app.modules.notebooks.domain.limits import NOTEBOOK_TITLE_MAX_CHARS
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker

UNFINISHED = (SourceStatus.PENDING, SourceStatus.PROCESSING)


class CopyNotebook:
    """Copies a notebook and its sources into a manual notebook of the same student.

    The student can add and remove sources in the copy and nothing changes it
    afterwards. The sources of the copy point at the same shared documents, so
    nothing is read, chunked or summarized again; chat history and Studio outputs
    are not copied.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        settings: Settings,
        i18n: I18nCore,
        locale: LocaleResolver,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.settings = settings
        self.i18n = i18n
        self.locale = locale
        self.kicker = kicker

    async def execute(self, actor: Actor, notebook_id: UUID) -> Notebook:
        """Store the copy (opened last) and return it.

        Raises:
            NotebookNotFoundError: The notebook is not the caller's.
            NotebookLimitError: The student already has the maximum of notebooks.
        """
        locale = await self.locale.locale_of(actor.user_id)
        async with self.uow_factory() as uow:
            original = await load_notebook(uow, actor.user_id, notebook_id, write=False)
            if original.is_course_workspace:
                raise WorkspaceActionError(params={"action": "copy"})
            if await uow.notebooks.count_live(actor.user_id) >= (
                self.settings.notebooks.max_notebooks
            ):
                raise NotebookLimitError(
                    params={"limit": self.settings.notebooks.max_notebooks}
                )
            sources = await uow.sources.list_for_notebook(original.id)
            copy = self._new_notebook(original, actor, locale)
            await uow.notebooks.add(copy)
            copied = [await self._copy_source(uow, copy, source) for source in sources]
            await copy_labels(
                uow,
                original.id,
                copy.id,
                {a.id: b.id for a, b in zip(sources, copied, strict=True)},
                self.clock.now(),
            )
            if _summary_is_current(original, sources):
                copy.summary = original.summary
                copy.summary_status = SummaryStatus.READY
                copy.summary_hash = selection_hash(copied)
            await sources_changed(uow, copy, self.clock.now())
            for source in copied:
                if source.status is SourceStatus.PENDING:
                    uow.after_commit(
                        partial(
                            self.kicker.kick,
                            "notebooks.process_source",
                            source_id=str(source.id),
                        )
                    )
            await uow.commit()
            stored = await uow.notebooks.get(copy.id)
        return stored or copy

    def _new_notebook(self, original: Notebook, actor: Actor, locale: str) -> Notebook:
        """The copy: manual, titled "<title> (copy)", with the same chat settings."""
        now = self.clock.now()
        title = self.i18n.t(locale, "notebooks-copy-title", title=original.title)
        if len(title) > NOTEBOOK_TITLE_MAX_CHARS:
            suffix = self.i18n.t(locale, "notebooks-copy-title", title="")
            room = NOTEBOOK_TITLE_MAX_CHARS - len(suffix)
            title = self.i18n.t(
                locale, "notebooks-copy-title", title=original.title[:room]
            )
        return Notebook(
            id=new_id(),
            owner_id=actor.user_id,
            title=title[:NOTEBOOK_TITLE_MAX_CHARS],
            title_auto=False,
            emoji=original.emoji,
            emoji_auto=False,
            created_at=now,
            updated_at=now,
            last_opened_at=now,
            chat_config=original.chat_config.model_copy(deep=True),
            origin=NotebookOrigin.MANUAL,
            space_key=original.space_key,
        )

    async def _copy_source(
        self, uow: NotebooksUnitOfWork, copy: Notebook, source: Source
    ) -> Source:
        """Store the source in the copy, with its passages when it has any."""
        now = self.clock.now()
        waiting = source.status in UNFINISHED
        clone = Source(
            id=new_id(),
            notebook_id=copy.id,
            owner_id=copy.owner_id,
            kind=source.kind,
            title=source.title,
            position=source.position,
            created_at=now,
            updated_at=now,
            ref=dict(source.ref),
            ref_key=source.ref_key,
            origin=None if source.origin is None else dict(source.origin),
            selected=source.selected,
            status=SourceStatus.PENDING if waiting else source.status,
            failure=None if waiting else source.failure,
            body_md=source.body_md,
            citations=source.citations,
            content_hash=None if waiting else source.content_hash,
            document_id=None if waiting else source.document_id,
            upstream_version=source.upstream_version,
            word_count=0 if waiting else source.word_count,
            char_count=0 if waiting else source.char_count,
            token_estimate=0 if waiting else source.token_estimate,
            passage_count=0 if waiting else source.passage_count,
            guide=None if waiting else source.guide,
            guide_status=_guide_status(source, waiting),
            text_synced_at=None if waiting else source.text_synced_at,
        )
        await uow.sources.add(clone)
        return clone


def _summary_is_current(original: Notebook, sources: list[Source]) -> bool:
    """True when the summary matches the sources, so the copy can keep it for free."""
    return (
        original.summary is not None
        and original.summary_status is SummaryStatus.READY
        and original.summary_hash == selection_hash(sources)
    )


def _guide_status(source: Source, waiting: bool) -> GuideStatus:
    """A guide that is still being written is not copied (the copy has none)."""
    if waiting or source.guide_status is GuideStatus.BUILDING:
        return GuideStatus.NONE
    return source.guide_status
