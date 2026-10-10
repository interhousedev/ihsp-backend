"""Use case: change what an auto notebook syncs (classmates' files, excluded files)."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook
from app.modules.notebooks.application.notebook_fields import invalid
from app.modules.notebooks.application.sync_auto_notebook import (
    SyncAutoNotebook,
    is_managed,
)
from app.modules.notebooks.domain.entities import AutoSettings, ExcludedRef, Notebook
from app.modules.notebooks.domain.limits import MAX_EXCLUDED_REFS
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock

EDITABLE = frozenset({"include_classmates", "exclude_source_ids", "restore_refs"})


class UpdateAutoSettings:
    """Applies a `PATCH /notebooks/{id}/auto` and syncs the notebook at once.

    An excluded material stays out on every later sync until it is restored.
    """

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, sync: SyncAutoNotebook
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.sync = sync

    async def execute(
        self, actor: Actor, notebook_id: UUID, changes: Mapping[str, Any]
    ) -> Notebook:
        """Change the settings, then bring the sources in line with them.

        Keys: `include_classmates` (bool), `exclude_source_ids` (sources of this
        notebook to leave out for good) and `restore_refs` (duplicate keys of
        excluded materials to take back). An unknown key or a bad value raises
        `InvalidOptionsError` and nothing is saved.

        Raises:
            NotebookNotFoundError: Not the caller's notebook.
            InvalidOptionsError: Not an auto notebook, or a bad key or value.
        """
        for key in changes:
            if key not in EDITABLE:
                raise invalid(key)
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, for_update=True
            )
            if notebook.auto_settings is None:
                raise invalid("origin")
            settings = await self._merged(uow, notebook, changes)
            if settings != notebook.auto_settings:
                notebook.auto_settings = settings
                notebook.updated_at = self.clock.now()
                await uow.notebooks.save(notebook)
            await uow.commit()
        await self.sync.execute(notebook_id)
        async with self.uow_factory() as uow:
            return await load_notebook(uow, actor.user_id, notebook_id)

    async def _merged(
        self, uow: NotebooksUnitOfWork, notebook: Notebook, changes: Mapping[str, Any]
    ) -> AutoSettings:
        """The settings with every change applied, or `InvalidOptionsError`."""
        current = notebook.auto_settings
        assert current is not None
        include = current.include_classmates
        if "include_classmates" in changes:
            include = _flag(changes["include_classmates"])
        excluded = list(current.excluded_refs)
        if "restore_refs" in changes:
            restored = set(_texts(changes["restore_refs"], "restore_refs"))
            excluded = [x for x in excluded if x.ref_key not in restored]
        if "exclude_source_ids" in changes:
            ids = _ids(changes["exclude_source_ids"])
            excluded = await self._exclude(uow, notebook, excluded, ids)
        if len(excluded) > MAX_EXCLUDED_REFS:
            raise invalid("exclude_source_ids")
        return AutoSettings(include_classmates=include, excluded_refs=excluded)

    @staticmethod
    async def _exclude(
        uow: NotebooksUnitOfWork,
        notebook: Notebook,
        excluded: list[ExcludedRef],
        source_ids: Sequence[UUID],
    ) -> list[ExcludedRef]:
        """Add the lesson materials and books among `source_ids`.

        Ids of other notebooks and of other kinds of sources are ignored.
        """
        known = {x.ref_key for x in excluded}
        result = list(excluded)
        for source in await uow.sources.get_many(source_ids):
            if (
                source.notebook_id == notebook.id
                and is_managed(source)
                and source.ref_key is not None
                and source.ref_key not in known
            ):
                known.add(source.ref_key)
                result.append(ExcludedRef(ref_key=source.ref_key, title=source.title))
        return result


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise invalid("include_classmates")
    return value


def _ids(value: object) -> list[UUID]:
    if not isinstance(value, list) or not all(isinstance(x, UUID) for x in value):
        raise invalid("exclude_source_ids")
    return list(value)


def _texts(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise invalid(field)
    return list(value)
