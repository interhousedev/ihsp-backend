"""Add a topic to a subject's tree (LIB-4, LIB-2)."""

from collections.abc import Mapping
from uuid import UUID

from app.modules.library.application.taxonomy.topic_views import manage_topic_view
from app.modules.library.application.taxonomy.views import ManageTopicView
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_errors import (
    TopicSlugTakenError,
    UnknownSubjectError,
)
from app.modules.library.domain.taxonomy_subjects import clean_code
from app.modules.library.domain.taxonomy_topics import (
    Topic,
    check_parent,
    clean_names,
    slug_from_names,
    unique_slug,
    validate_slug,
)
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft


class CreateTopic:
    """`POST /v1/manage/library/topics`: a librarian adds a topic."""

    def __init__(
        self, *, uow_factory: UowFactory, academic: AcademicDirectory, clock: Clock
    ) -> None:
        """Store the unit of work factory, the subjects and the clock."""
        self.uow_factory = uow_factory
        self.academic = academic
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        *,
        subject_id: UUID,
        name: Mapping[str, str],
        parent_id: UUID | None = None,
        slug: str | None = None,
        year_of_study: int | None = None,
        code: str | None = None,
    ) -> ManageTopicView:
        """Create the topic last among its siblings.

        A slug that was not chosen comes from the name and gets a number when a
        sibling already uses it; a chosen one that is taken is a conflict.
        """
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        names = clean_names(name)
        if subject_id not in await self.academic.subject_names([subject_id], "en"):
            raise UnknownSubjectError(params={"subject_id": str(subject_id)})
        async with self.uow_factory() as uow:
            topics = await uow.taxonomy.topics(subject_id)
            if parent_id is not None:
                check_parent(topics, subject_id=subject_id, parent_id=parent_id)
            siblings = [t for t in topics if t.parent_id == parent_id]
            taken = {t.slug for t in siblings}
            if slug is not None:
                if validate_slug(slug) in taken:
                    raise TopicSlugTakenError(params={"slug": slug})
                chosen = slug
            else:
                chosen = unique_slug(slug_from_names(names), taken)
            now = self.clock.now()
            topic = Topic(
                id=new_id(),
                subject_id=subject_id,
                parent_id=parent_id,
                name=names,
                slug=chosen,
                position=max((t.position for t in siblings), default=-1) + 1,
                year_of_study=year_of_study,
                created_at=now,
                updated_at=now,
                code=clean_code(code),
            )
            await uow.taxonomy.add_topic(topic)
            uow.audit(
                AuditDraft(
                    type=TaxonomyAuditType.TOPIC_CREATE.value,
                    actor_id=actor.user_id,
                    metadata={
                        "topic_id": str(topic.id),
                        "subject_id": str(subject_id),
                        "slug": chosen,
                    },
                )
            )
            await uow.commit()
        return manage_topic_view(topic)
