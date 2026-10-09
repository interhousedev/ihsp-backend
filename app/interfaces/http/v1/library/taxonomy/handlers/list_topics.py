"""GET /v1/library/topics?subject_id."""

from uuid import UUID

from app.interfaces.http.v1.library.deps import AcceptLanguage, Library, MaybeSignedIn
from app.interfaces.http.v1.library.taxonomy.schemas_taxonomy import TopicResponse


async def list_topics(
    library: Library,
    actor: MaybeSignedIn,
    accept_language: AcceptLanguage = None,
    subject_id: UUID | None = None,
) -> list[TopicResponse]:
    """The topic tree of a subject (of every subject without `subject_id`)."""
    views = await library.taxonomy.list_topics.execute(
        actor, subject_id=subject_id, accept_language=accept_language
    )
    return [TopicResponse.from_view(view) for view in views]
