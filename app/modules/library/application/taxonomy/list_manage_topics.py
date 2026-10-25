"""List topics flat with all names, for the librarian's editor (LIB-4)."""

from uuid import UUID

from app.modules.library.application.taxonomy.topic_views import manage_topic_view
from app.modules.library.application.taxonomy.views import ManageTopicView
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role


class ListManageTopics:
    """`GET /v1/manage/library/topics`."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(
        self, actor: Actor, *, subject_id: UUID | None = None
    ) -> list[ManageTopicView]:
        """Topics of the subject (or of all) in tree order of positions."""
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        async with self.uow_factory() as uow:
            topics = await uow.taxonomy.topics(subject_id)
        return [manage_topic_view(topic) for topic in topics]
