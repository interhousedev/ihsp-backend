"""Attached notebooks: live source sets, re-checked on every use (NB-SHARE)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.domain.entities import Notebook, Source
from app.modules.notebooks.domain.errors import (
    NotebookNotFoundError,
    ShareLimitError,
    ShareUnsupportedError,
)
from app.modules.notebooks.domain.sharing import (
    MAX_LINKED_SETS,
    VIEWABLE_KINDS,
    LinkedSet,
    is_shareable,
    viewable,
)
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class LinkedSetView:
    """An attached notebook; nothing but its id once access is gone."""

    notebook_id: UUID
    available: bool
    title: str | None
    emoji: str | None
    sources: list[Source]


async def readable_linked(
    uow: NotebooksUnitOfWork, user_id: UUID, linked_id: UUID
) -> Notebook | None:
    """The attached notebook if the user may still read it, else None."""
    try:
        notebook = await load_notebook(
            uow, user_id, linked_id, write=False, shared=True
        )
    except NotebookNotFoundError:
        return None
    return notebook if is_shareable(notebook) else None


async def linked_sources(
    uow: NotebooksUnitOfWork, user_id: UUID, host: Notebook
) -> list[Source]:
    """Usable sources of the sets attached to the host, for its owner only.

    A viewer of the host gets none: a share never passes on what the owner attached.
    Sets are not followed further than one step.
    """
    if host.owner_id != user_id:
        return []
    found: list[Source] = []
    for linked in await uow.shares.linked_sets(host.id):
        notebook = await readable_linked(uow, user_id, linked.linked_notebook_id)
        if notebook is not None:
            sources = await uow.sources.list_for_notebook(notebook.id)
            found.extend(s for s in viewable(sources) if s.usable)
    return found


async def attached_source(
    uow: NotebooksUnitOfWork, user_id: UUID, host_id: UUID, source_id: UUID
) -> Source:
    """A viewable source of a set attached to the host, for the host's owner only.

    The grant on the attached notebook is checked again on every call (through
    `readable_linked`), so a revoked share closes the viewer at once.

    Raises:
        NotebookNotFoundError: The host is not the caller's, the set is detached or
            no longer readable, or the source is not in it or not viewable.
    """
    host = await load_notebook(uow, user_id, host_id, write=False)
    if host.owner_id != user_id:
        raise NotebookNotFoundError()
    found = await uow.sources.get(source_id)
    if found is None:
        raise NotebookNotFoundError()
    for linked in await uow.shares.linked_sets(host.id):
        if linked.linked_notebook_id != found.notebook_id:
            continue
        notebook = await readable_linked(uow, user_id, linked.linked_notebook_id)
        if (
            notebook is not None
            and found.owner_id == notebook.owner_id
            and found.kind in VIEWABLE_KINDS
        ):
            return found
    raise NotebookNotFoundError()


class LinkedSets:
    """Lists, attaches and detaches the source sets of the owner's notebook."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def _host(
        self, uow: NotebooksUnitOfWork, actor: Actor, notebook_id: UUID
    ) -> Notebook:
        host = await load_notebook(uow, actor.user_id, notebook_id, write=True)
        if host.owner_id != actor.user_id:
            raise NotebookNotFoundError()
        return host

    async def list(self, actor: Actor, notebook_id: UUID) -> list[LinkedSetView]:
        """Every attached set; one without access shows as unavailable and empty."""
        views: list[LinkedSetView] = []
        async with self.uow_factory() as uow:
            host = await self._host(uow, actor, notebook_id)
            for linked in await uow.shares.linked_sets(host.id):
                notebook = await readable_linked(
                    uow, actor.user_id, linked.linked_notebook_id
                )
                if notebook is None:
                    views.append(
                        LinkedSetView(linked.linked_notebook_id, False, None, None, [])
                    )
                    continue
                sources = await uow.sources.list_for_notebook(notebook.id)
                views.append(
                    LinkedSetView(
                        notebook.id,
                        True,
                        notebook.title,
                        notebook.emoji,
                        viewable(sources),
                    )
                )
        return views

    async def attach(self, actor: Actor, notebook_id: UUID, linked_id: UUID) -> None:
        """Attach a notebook the caller owns or that is shared with them.

        Raises:
            NotebookNotFoundError: Either notebook is not available to the caller.
            ShareUnsupportedError: The host is not a manual notebook, or is the set.
            ShareLimitError: The host already has 3 sets.
        """
        async with self.uow_factory() as uow:
            host = await self._host(uow, actor, notebook_id)
            if not is_shareable(host) or linked_id == notebook_id:
                raise ShareUnsupportedError()
            if await readable_linked(uow, actor.user_id, linked_id) is None:
                raise NotebookNotFoundError()
            current = await uow.shares.linked_sets(notebook_id)
            if len(current) >= MAX_LINKED_SETS:
                raise ShareLimitError(params={"limit": MAX_LINKED_SETS})
            await uow.shares.add_linked_set(
                LinkedSet(notebook_id, linked_id, self.clock.now())
            )
            await uow.commit()

    async def detach(self, actor: Actor, notebook_id: UUID, linked_id: UUID) -> None:
        """Detach a set; it works for a set the caller lost access to as well."""
        async with self.uow_factory() as uow:
            await self._host(uow, actor, notebook_id)
            await uow.shares.remove_linked_set(notebook_id, linked_id)
            await uow.commit()
