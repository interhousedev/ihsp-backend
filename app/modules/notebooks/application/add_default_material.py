"""Use case: add a default material to an EMIS subject id (admin)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.notebooks.application.readers.url_reader import normalise_url
from app.modules.notebooks.domain.default_materials import (
    DEFAULT_MATERIAL_TITLE_MAX_CHARS,
    MAX_DEFAULT_MATERIALS,
    DefaultMaterial,
    DefaultMaterialKind,
)
from app.modules.notebooks.domain.errors import (
    DefaultMaterialExistsError,
    DefaultMaterialInvalidError,
    DefaultMaterialLimitError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class DefaultMaterialDraft:
    """What the admin sends: the kind, a title and the one target of the kind."""

    kind: DefaultMaterialKind
    title: str
    url: str | None = None
    file_id: UUID | None = None
    library_item_id: UUID | None = None


class AddDefaultMaterial:
    """Adds a material every student's subject notebook of the EMIS id gets.

    A file must be one the admin uploaded and that exists; a link is normalised like a
    student's URL source (a bad one is refused). A library item is checked for access
    per student at sync, so an item a student may not read is simply not copied.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        files: FilesApi | None,
    ) -> None:
        """Store the collaborators (`files` None: file materials are refused)."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.files = files

    async def execute(
        self, actor: Actor, edu_subject_id: int, draft: DefaultMaterialDraft
    ) -> DefaultMaterial:
        """Store the material at the end of the subject's list and return it.

        Raises:
            DefaultMaterialInvalidError: The file, link or item cannot be used.
            DefaultMaterialExistsError: The subject has this target already.
            DefaultMaterialLimitError: The subject has the maximum already.
        """
        title = draft.title.strip()[:DEFAULT_MATERIAL_TITLE_MAX_CHARS]
        if not title:
            raise DefaultMaterialInvalidError(params={"field": "title"})
        url, file_id, item_id = await self._target(actor, draft)
        async with self.uow_factory() as uow:
            current = await uow.default_materials.list_for_subject(edu_subject_id)
            if len(current) >= MAX_DEFAULT_MATERIALS:
                raise DefaultMaterialLimitError(params={"limit": MAX_DEFAULT_MATERIALS})
            material = DefaultMaterial(
                id=new_id(),
                edu_subject_id=edu_subject_id,
                kind=draft.kind,
                title=title,
                position=max((x.position for x in current), default=-1) + 1,
                created_by=actor.user_id,
                created_at=self.clock.now(),
                file_id=file_id,
                url=url,
                library_item_id=item_id,
            )
            if any(material.same_target(other) for other in current):
                raise DefaultMaterialExistsError()
            await uow.default_materials.add(material)
            await uow.commit()
        return material

    async def _target(
        self, actor: Actor, draft: DefaultMaterialDraft
    ) -> tuple[str | None, UUID | None, UUID | None]:
        """The (url, file id, library item id) of the kind, each checked."""
        if draft.kind is DefaultMaterialKind.FILE:
            return None, await self._own_file(actor, draft.file_id), None
        if draft.kind is DefaultMaterialKind.LINK:
            return self._link(draft.url), None, None
        if draft.library_item_id is None:
            raise DefaultMaterialInvalidError(params={"field": "library_item_id"})
        return None, None, draft.library_item_id

    async def _own_file(self, actor: Actor, file_id: UUID | None) -> UUID:
        """A file the admin uploaded: only their own files may be shared out."""
        if file_id is None or self.files is None:
            raise DefaultMaterialInvalidError(params={"field": "file_id"})
        ref = await self.files.get(file_id)
        if ref is None or ref.status == "deleted" or ref.owner_id != actor.user_id:
            raise DefaultMaterialInvalidError(params={"field": "file_id"})
        return file_id

    @staticmethod
    def _link(raw: str | None) -> str:
        if not raw:
            raise DefaultMaterialInvalidError(params={"field": "url"})
        try:
            return normalise_url(raw)
        except BaseError as exc:
            raise DefaultMaterialInvalidError(params={"field": "url"}) from exc
