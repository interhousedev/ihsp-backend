"""GET /v1/manage/library/topics?subject_id."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import (
    ManageTopicResponse,
)


async def list_manage_topics(
    library: Library, actor: LibrarianActor, subject_id: UUID | None = None
) -> list[ManageTopicResponse]:
    """Topics with all three names, flat, in tree order."""
    views = await library.taxonomy.list_manage_topics.execute(
        actor, subject_id=subject_id
    )
    return [ManageTopicResponse.from_view(view) for view in views]
