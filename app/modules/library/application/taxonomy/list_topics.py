"""List the topic tree of a subject (or of all subjects) for any reader (LIB-4)."""

from uuid import UUID

from app.modules.library.application.locale import resolve_locale
from app.modules.library.application.taxonomy.topic_views import topic_views
from app.modules.library.application.taxonomy.views import TopicView
from app.modules.library.domain.taxonomy_topics import build_tree
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class ListTopics:
    """`GET /v1/library/topics`: the tree with names in the reader's language."""

    def __init__(self, *, uow_factory: UowFactory, identity: IdentityDirectory) -> None:
        """Store the unit of work factory and the user directory."""
        self.uow_factory = uow_factory
        self.identity = identity

    async def execute(
        self,
        viewer: Actor | None,
        *,
        subject_id: UUID | None = None,
        accept_language: str | None = None,
    ) -> list[TopicView]:
        """Root topics with their children, ordered by position."""
        locale = await resolve_locale(self.identity, viewer, accept_language)
        async with self.uow_factory() as uow:
            topics = await uow.taxonomy.topics(subject_id)
        return topic_views(build_tree(topics), locale)
