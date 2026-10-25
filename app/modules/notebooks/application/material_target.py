"""The draft of a subject material and the check of its file, link or library item."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.notebooks.application.readers.url_reader import normalise_url
from app.modules.notebooks.domain.default_materials import DefaultMaterialKind
from app.modules.notebooks.domain.errors import DefaultMaterialInvalidError
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.contracts.files import FilesApi


@dataclass(frozen=True, slots=True)
class DefaultMaterialDraft:
    """What the admin or teacher sends: the kind, a title and the one target."""

    kind: DefaultMaterialKind
    title: str
    url: str | None = None
    file_id: UUID | None = None
    library_item_id: UUID | None = None


async def check_target(
    files: FilesApi | None, actor: Actor, draft: DefaultMaterialDraft
) -> tuple[str | None, UUID | None, UUID | None]:
    """The (url, file id, library item id) of the kind, each checked.

    Raises:
        DefaultMaterialInvalidError: The file, link or item cannot be used.
    """
    if draft.kind is DefaultMaterialKind.FILE:
        return None, await _own_file(files, actor, draft.file_id), None
    if draft.kind is DefaultMaterialKind.LINK:
        return _link(draft.url), None, None
    if draft.library_item_id is None:
        raise DefaultMaterialInvalidError(params={"field": "library_item_id"})
    return None, None, draft.library_item_id


async def _own_file(files: FilesApi | None, actor: Actor, file_id: UUID | None) -> UUID:
    """A file the user uploaded: only their own files may be shared out."""
    if file_id is None or files is None:
        raise DefaultMaterialInvalidError(params={"field": "file_id"})
    ref = await files.get(file_id)
    if ref is None or ref.status == "deleted" or ref.owner_id != actor.user_id:
        raise DefaultMaterialInvalidError(params={"field": "file_id"})
    return file_id


def _link(raw: str | None) -> str:
    if not raw:
        raise DefaultMaterialInvalidError(params={"field": "url"})
    try:
        return normalise_url(raw)
    except BaseError as exc:
        raise DefaultMaterialInvalidError(params={"field": "url"}) from exc
