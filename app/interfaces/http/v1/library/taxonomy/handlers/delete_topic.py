"""DELETE /v1/manage/library/topics/{topic_id}."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import LibrarianActor, Library


async def delete_topic(topic_id: UUID, library: Library, actor: LibrarianActor) -> None:
    """Delete a topic with its sub-topics; items keep existing."""
    await library.taxonomy.delete_topic.execute(actor, topic_id)
