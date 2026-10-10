"""Routes handlers of /v1/manage/library/subjects."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import (
    CreateSubjectBody,
    ManageSubjectResponse,
    UpdateSubjectBody,
    sent,
)
from app.modules.library.domain.taxonomy_unset import UNSET


async def list_manage_subjects(
    library: Library, actor: LibrarianActor
) -> list[ManageSubjectResponse]:
    """Every subject with all names, archived ones included."""
    views = await library.taxonomy.list_manage_subjects.execute(actor)
    return [ManageSubjectResponse.from_view(view) for view in views]


async def create_subject(
    body: CreateSubjectBody, library: Library, actor: LibrarianActor
) -> ManageSubjectResponse:
    """Create a subject (librarians and Administration)."""
    view = await library.taxonomy.create_subject.execute(
        actor,
        name=body.name.to_dict(),
        parent_id=body.parent_id,
        code=body.code,
        slug=body.slug,
    )
    return ManageSubjectResponse.from_view(view)


async def update_subject(
    subject_id: UUID, body: UpdateSubjectBody, library: Library, actor: LibrarianActor
) -> ManageSubjectResponse:
    """Change the sent fields: rename, re-code, nest, reorder, archive."""
    view = await library.taxonomy.update_subject.execute(
        actor,
        subject_id,
        name=body.name.to_dict() if body.name is not None else UNSET,
        slug=body.slug if body.slug is not None else UNSET,
        parent_id=sent(body, "parent_id", body.parent_id),
        code=sent(body, "code", body.code),
        archived=body.archived if body.archived is not None else UNSET,
        position=body.position if body.position is not None else UNSET,
    )
    return ManageSubjectResponse.from_view(view)


async def delete_subject(
    subject_id: UUID, library: Library, actor: LibrarianActor
) -> None:
    """Delete an unused subject without children; others are archived."""
    await library.taxonomy.delete_subject.execute(actor, subject_id)
