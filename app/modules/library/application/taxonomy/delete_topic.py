"""Delete a topic with everything under it (LIB-4, LIB-2)."""

from uuid import UUID

from app.modules.library.domain.errors import TopicNotFoundError
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_topics import descendant_ids
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.notifications import AuditDraft


class DeleteTopic:
    """`DELETE /v1/manage/library/topics/{id}`: the subtree and item links go."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, topic_id: UUID) -> None:
        """Delete the topic, its children and their links to items.

        Reading list entries keep their row but lose the topic. The audit event
        records how many topics and item links were removed.
        """
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        async with self.uow_factory() as uow:
            topic = await uow.taxonomy.get_topic(topic_id)
            if topic is None:
                raise TopicNotFoundError(params={"topic_id": str(topic_id)})
            topics = await uow.taxonomy.topics(topic.subject_id)
            doomed = {topic.id} | descendant_ids(topics, topic.id)
            links = await uow.taxonomy.count_item_links(doomed)
            await uow.lists.clear_topic(doomed)
            await uow.taxonomy.delete_topic(topic.id)
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.TOPIC_DELETE.value,
                    actor_id=actor.user_id,
                    metadata={
                        "topic_id": str(topic.id),
                        "subject_id": str(topic.subject_id),
                        "slug": topic.slug,
                        "topics_removed": len(doomed),
                        "item_links_removed": links,
                    },
                )
            )
            await uow.commit()
