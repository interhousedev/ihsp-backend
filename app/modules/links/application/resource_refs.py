"""Mapping resource views to the cross-module ResourceRef."""

from app.modules.links.application.views import ResourceView
from app.modules.links.domain.link import LessonRole, LinkKind
from app.shared.contracts.links import EMIS_AUTHOR_ID, ResourceRef


def to_ref(view: ResourceView) -> ResourceRef:
    """Convert a ResourceView of a lesson resource into a ResourceRef."""
    link = view.link
    assert link.lesson_id is not None and link.lesson_role is not None
    role = LessonRole(link.lesson_role).value
    return ResourceRef(
        link_id=link.id,
        lesson_id=link.lesson_id,
        role=role,  # type: ignore[arg-type]
        kind="file" if link.kind is LinkKind.FILE else "url",
        short_url=view.short_url,
        title=view.title,
        author_id=link.owner_id,
        author_first_name=view.author.first_name,
        hidden=link.is_hidden,
        file_id=link.file_id,
        source="emis" if link.owner_id == EMIS_AUTHOR_ID else "user",
        file=view.file,
        created_at=link.created_at,
        target_url=link.target_url,
    )
