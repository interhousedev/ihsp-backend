"""PATCH /v1/manage/library/topics/{topic_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import LibrarianActor, Library
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import (
    ManageTopicResponse,
    UpdateTopicBody,
    sent,
)
from app.modules.library.domain.taxonomy_unset import UNSET


async def update_topic(
    topic_id: UUID, body: UpdateTopicBody, library: Library, actor: LibrarianActor
) -> ManageTopicResponse:
    """Change the sent fields of a topic."""
    view = await library.taxonomy.update_topic.execute(
        actor,
        topic_id,
        name=body.name.to_dict() if body.name is not None else UNSET,
        slug=body.slug if body.slug is not None else UNSET,
        parent_id=sent(body, "parent_id", body.parent_id),
        year_of_study=sent(body, "year_of_study", body.year_of_study),
        subject_id=body.subject_id if body.subject_id is not None else UNSET,
        code=sent(body, "code", body.code),
        archived=body.archived if body.archived is not None else UNSET,
        position=body.position if body.position is not None else UNSET,
    )
    return ManageTopicResponse.from_view(view)
