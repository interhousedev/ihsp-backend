"""POST /v1/manage/library/topics."""

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import (
    CreateTopicBody,
    ManageTopicResponse,
)


async def create_topic(
    body: CreateTopicBody, library: Library, actor: LibrarianActor
) -> ManageTopicResponse:
    """Create a topic (librarians and Administration)."""
    view = await library.taxonomy.create_topic.execute(
        actor,
        subject_id=body.subject_id,
        name=body.name.to_dict(),
        parent_id=body.parent_id,
        slug=body.slug,
        year_of_study=body.year_of_study,
        code=body.code,
    )
    return ManageTopicResponse.from_view(view)
