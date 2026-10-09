"""Rename, re-slug, re-date or move a topic (LIB-4, LIB-2)."""

from collections.abc import Mapping
from uuid import UUID

from app.modules.library.application.taxonomy.topic_views import manage_topic_view
from app.modules.library.application.taxonomy.views import ManageTopicView
from app.modules.library.domain.errors import TopicNotFoundError
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_errors import (
    TopicSlugTakenError,
    TopicSubjectFixedError,
)
from app.modules.library.domain.taxonomy_topics import (
    Topic,
    check_parent,
    clean_names,
    validate_slug,
)
from app.modules.library.domain.taxonomy_unset import UNSET, Unset
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft


class UpdateTopic:
    """`PATCH /v1/manage/library/topics/{id}`: only the fields that were sent."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        topic_id: UUID,
        *,
        name: Mapping[str, str] | Unset = UNSET,
        slug: str | Unset = UNSET,
        parent_id: UUID | None | Unset = UNSET,
        year_of_study: int | None | Unset = UNSET,
        subject_id: UUID | Unset = UNSET,
    ) -> ManageTopicView:
        """Apply the given changes; `None` clears the year or moves to the root.

        A topic never changes subject (`subject_id` is accepted only when equal),
        and a rename keeps the slug, so links to the topic stay valid.
        """
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        async with self.uow_factory() as uow:
            topic = await uow.taxonomy.get_topic(topic_id)
            if topic is None:
                raise TopicNotFoundError(params={"topic_id": str(topic_id)})
            if not isinstance(subject_id, Unset) and subject_id != topic.subject_id:
                raise TopicSubjectFixedError(params={"topic_id": str(topic_id)})
            topics = await uow.taxonomy.topics(topic.subject_id)
            if not isinstance(name, Unset):
                topic.name = clean_names(name)
            if not isinstance(year_of_study, Unset):
                topic.year_of_study = year_of_study
            if not isinstance(parent_id, Unset):
                self._move(topic, topics, parent_id)
            if not isinstance(slug, Unset):
                topic.slug = validate_slug(slug)
            self._check_slug(topic, topics)
            topic.updated_at = self.clock.now()
            await uow.taxonomy.save_topic(topic)
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.TOPIC_UPDATE.value,
                    actor_id=actor.user_id,
                    metadata={"topic_id": str(topic.id), "slug": topic.slug},
                )
            )
            await uow.commit()
        return manage_topic_view(topic)

    @staticmethod
    def _move(topic: Topic, topics: list[Topic], parent_id: UUID | None) -> None:
        """Put the topic last under the new parent (or at the root)."""
        if parent_id == topic.parent_id:
            return
        if parent_id is not None:
            check_parent(
                topics,
                subject_id=topic.subject_id,
                parent_id=parent_id,
                topic_id=topic.id,
            )
        siblings = [t for t in topics if t.parent_id == parent_id and t.id != topic.id]
        topic.parent_id = parent_id
        topic.position = max((t.position for t in siblings), default=-1) + 1

    @staticmethod
    def _check_slug(topic: Topic, topics: list[Topic]) -> None:
        """No sibling under the (new) parent may have the slug."""
        if any(
            t.slug == topic.slug and t.parent_id == topic.parent_id and t.id != topic.id
            for t in topics
        ):
            raise TopicSlugTakenError(params={"slug": topic.slug})
