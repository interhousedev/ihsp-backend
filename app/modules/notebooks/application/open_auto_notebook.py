"""Use case: open (or look up) the subject or lesson notebook of a student."""

from functools import partial
from uuid import UUID

from app.modules.notebooks.application.auto_targets import AutoTarget, AutoTargets
from app.modules.notebooks.application.sync_auto_notebook import SyncAutoNotebook
from app.modules.notebooks.domain.auto_notebook import sync_is_stale
from app.modules.notebooks.domain.entities import AutoSettings, Notebook
from app.modules.notebooks.domain.enums import NotebookOrigin
from app.modules.notebooks.domain.errors import (
    AutoNotebookLimitError,
    InvalidOptionsError,
    NotebookNotFoundError,
)
from app.modules.notebooks.domain.limits import MAX_AUTO_NOTEBOOKS
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.tasks import TaskKicker


class OpenAutoNotebook:
    """Get-or-create of the "Subject notebook" and the "Lesson notebook".

    The notebook is the student's own, kept by the system: its sources are the
    lesson materials of the subject (this term) or of the lesson. The first time it
    is filled right away, so the student sees sources when the page opens; after
    that the sync job keeps it current.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        targets: AutoTargets,
        sync: SyncAutoNotebook,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.targets = targets
        self.sync = sync
        self.kicker = kicker

    async def execute(
        self,
        actor: Actor,
        origin: NotebookOrigin,
        target_id: UUID,
        *,
        create: bool = True,
        group_id: UUID | None = None,
    ) -> Notebook:
        """Return the student's notebook for the subject or lesson.

        A teacher passes the `group_id` they teach the subject to: their notebook is
        one per subject and group.

        With `create=False` only an existing one is returned and nothing is touched
        (the card on the subject page); otherwise it is created when missing and
        counts as opened.

        Raises:
            InvalidOptionsError: `origin` is `manual`.
            NotebookNotFoundError: No such notebook (`create=False`), or the student
                has no such subject or lesson.
            AutoNotebookLimitError: Too many subject and lesson notebooks.
        """
        if not origin.is_auto:
            raise InvalidOptionsError(params={"field": "origin"})
        found = await self._existing(actor, origin, target_id, group_id, touch=create)
        if found is not None:
            return found
        if not create:
            raise NotebookNotFoundError()
        target = await self.targets.resolve(actor.user_id, origin, target_id, group_id)
        if target is None:
            raise NotebookNotFoundError()
        created = await self._create(actor, target)
        if created is None:  # a parallel request made it first
            existing = await self._existing(
                actor, origin, target_id, group_id, touch=True
            )
            if existing is None:
                raise NotebookNotFoundError()
            return existing
        await self.sync.execute(created.id)
        return await self._reload(created.id)

    async def _existing(
        self,
        actor: Actor,
        origin: NotebookOrigin,
        target_id: UUID,
        group_id: UUID | None,
        *,
        touch: bool,
    ) -> Notebook | None:
        """Return the notebook if there is one.

        Opening it (`touch`) makes it the last opened and syncs it again when the
        last sync was a while ago.
        """
        async with self.uow_factory() as uow:
            notebook = await uow.notebooks.find_auto(
                actor.user_id, origin, target_id, group_id
            )
            if notebook is None or not touch:
                return notebook
            now = self.clock.now()
            notebook.last_opened_at = now
            await uow.notebooks.save(notebook)
            if sync_is_stale(notebook.auto_synced_at, now):
                uow.after_commit(
                    partial(
                        self.kicker.kick,
                        "notebooks.sync_auto_notebook",
                        notebook_id=str(notebook.id),
                    )
                )
            await uow.commit()
        return notebook

    async def _create(self, actor: Actor, target: AutoTarget) -> Notebook | None:
        """Store the empty notebook; None when the student already has it."""
        now = self.clock.now()
        notebook = Notebook(
            id=new_id(),
            owner_id=actor.user_id,
            title=target.title,
            title_auto=False,
            emoji=target.emoji,
            emoji_auto=False,
            created_at=now,
            updated_at=now,
            last_opened_at=now,
            origin=target.origin,
            subject_id=target.subject_id,
            lesson_id=target.lesson_id,
            group_id=target.group_id,
            auto_settings=AutoSettings(),
            space_key=target.space_key,
        )
        async with self.uow_factory() as uow:
            await self._check_limit(uow, actor)
            if not await uow.notebooks.add_auto(notebook):
                return None
            await uow.commit()
        return notebook

    @staticmethod
    async def _check_limit(uow: NotebooksUnitOfWork, actor: Actor) -> None:
        if await uow.notebooks.count_live_auto(actor.user_id) >= MAX_AUTO_NOTEBOOKS:
            raise AutoNotebookLimitError(params={"limit": MAX_AUTO_NOTEBOOKS})

    async def _reload(self, notebook_id: UUID) -> Notebook:
        """The notebook with fresh source counts."""
        async with self.uow_factory() as uow:
            notebook = await uow.notebooks.get(notebook_id)
        if notebook is None:
            raise NotebookNotFoundError()
        return notebook
