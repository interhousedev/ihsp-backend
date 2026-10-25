"""Librarian-managed subjects: list, create, rename/nest/reorder/archive, delete."""

from collections.abc import Mapping
from uuid import UUID

from app.modules.library.application.taxonomy.views import ManageSubjectView
from app.modules.library.domain.errors import SubjectNotFoundError
from app.modules.library.domain.taxonomy_audit import TaxonomyAuditType
from app.modules.library.domain.taxonomy_errors import (
    SubjectInUseError,
    SubjectSlugTakenError,
)
from app.modules.library.domain.taxonomy_subjects import (
    Subject,
    check_subject_parent,
    clean_code,
    subject_descendants,
)
from app.modules.library.domain.taxonomy_topics import (
    clean_names,
    slug_from_names,
    unique_slug,
    validate_slug,
)
from app.modules.library.domain.taxonomy_unset import UNSET, Unset
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft


def manage_subject_view(subject: Subject) -> ManageSubjectView:
    """A subject with all three names."""
    return ManageSubjectView(
        id=subject.id,
        parent_id=subject.parent_id,
        name=dict(subject.name),
        slug=subject.slug,
        code=subject.code,
        position=subject.position,
        archived=subject.archived,
    )


def _audit(
    uow: LibraryUnitOfWork, actor: Actor, kind: TaxonomyAuditType, subject: Subject
) -> None:
    uow.audit(
        AuditDraft(
            type=kind.value,
            actor_id=actor.user_id,
            metadata={"subject_id": str(subject.id), "slug": subject.slug},
        )
    )


class ListManageSubjects:
    """`GET /v1/manage/library/subjects`: every subject, archived ones included."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor) -> list[ManageSubjectView]:
        """Subjects by parent and position."""
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        async with self.uow_factory() as uow:
            subjects = await uow.taxonomy.subjects()
        return [manage_subject_view(s) for s in subjects]


class CreateSubject:
    """`POST /v1/manage/library/subjects`."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        *,
        name: Mapping[str, str],
        parent_id: UUID | None = None,
        code: str | None = None,
        slug: str | None = None,
    ) -> ManageSubjectView:
        """Create the subject last among its siblings."""
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        names = clean_names(name)
        async with self.uow_factory() as uow:
            subjects = await uow.taxonomy.subjects()
            if parent_id is not None:
                check_subject_parent(subjects, parent_id=parent_id)
            siblings = [s for s in subjects if s.parent_id == parent_id]
            taken = {s.slug for s in siblings}
            if slug is not None:
                if validate_slug(slug) in taken:
                    raise SubjectSlugTakenError(params={"slug": slug})
                chosen = slug
            else:
                chosen = unique_slug(slug_from_names(names), taken)
            now = self.clock.now()
            subject = Subject(
                id=new_id(),
                parent_id=parent_id,
                name=names,
                slug=chosen,
                position=max((s.position for s in siblings), default=-1) + 1,
                created_at=now,
                updated_at=now,
                code=clean_code(code),
            )
            await uow.taxonomy.add_subject(subject)
            _audit(uow, actor, TaxonomyAuditType.SUBJECT_CREATE, subject)
            await uow.commit()
        return manage_subject_view(subject)


def _move(subject: Subject, subjects: list[Subject], parent_id: UUID | None) -> None:
    """Nest the subject last under the new parent (or at the root)."""
    if parent_id == subject.parent_id:
        return
    if parent_id is not None:
        check_subject_parent(subjects, parent_id=parent_id, subject_id=subject.id)
    siblings = [s for s in subjects if s.parent_id == parent_id and s.id != subject.id]
    subject.parent_id = parent_id
    subject.position = max((s.position for s in siblings), default=-1) + 1


def _check_slug(subject: Subject, subjects: list[Subject]) -> None:
    """No sibling under the (new) parent may have the slug."""
    if any(
        s.slug == subject.slug
        and s.parent_id == subject.parent_id
        and s.id != subject.id
        for s in subjects
    ):
        raise SubjectSlugTakenError(params={"slug": subject.slug})


class UpdateSubject:
    """`PATCH /v1/manage/library/subjects/{id}`: only the fields that were sent."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        subject_id: UUID,
        *,
        name: Mapping[str, str] | Unset = UNSET,
        slug: str | Unset = UNSET,
        parent_id: UUID | None | Unset = UNSET,
        code: str | None | Unset = UNSET,
        archived: bool | Unset = UNSET,
        position: int | Unset = UNSET,
    ) -> ManageSubjectView:
        """Rename, re-code, nest under another subject, reorder or archive."""
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        async with self.uow_factory() as uow:
            subjects = await uow.taxonomy.subjects()
            subject = next((s for s in subjects if s.id == subject_id), None)
            if subject is None:
                raise SubjectNotFoundError(params={"subject_id": str(subject_id)})
            now = self.clock.now()
            if not isinstance(name, Unset):
                subject.name = clean_names(name)
            if not isinstance(code, Unset):
                subject.code = clean_code(code)
            if not isinstance(parent_id, Unset):
                _move(subject, subjects, parent_id)
            if not isinstance(slug, Unset):
                subject.slug = validate_slug(slug)
            _check_slug(subject, subjects)
            if not isinstance(archived, Unset):
                subject.archived_at = (subject.archived_at or now) if archived else None
            subject.updated_at = now
            if not isinstance(position, Unset):
                await self._reorder(uow, subject, subjects, position)
            await uow.taxonomy.save_subject(subject)
            _audit(uow, actor, TaxonomyAuditType.SUBJECT_UPDATE, subject)
            await uow.commit()
        return manage_subject_view(subject)

    @staticmethod
    async def _reorder(
        uow: LibraryUnitOfWork,
        subject: Subject,
        subjects: list[Subject],
        position: int,
    ) -> None:
        """Put the subject at `position` among its siblings, renumbering them 0..n."""
        siblings = sorted(
            (
                s
                for s in subjects
                if s.parent_id == subject.parent_id and s.id != subject.id
            ),
            key=lambda s: (s.position, s.slug),
        )
        siblings.insert(max(0, min(position, len(siblings))), subject)
        for index, sibling in enumerate(siblings):
            if sibling.position != index:
                sibling.position = index
                if sibling.id != subject.id:
                    await uow.taxonomy.save_subject(sibling)


class DeleteSubject:
    """`DELETE /v1/manage/library/subjects/{id}`: only an unused, childless subject."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, subject_id: UUID) -> None:
        """Delete it; a subject with books, topics or sub-subjects must be archived."""
        actor.require(Role.LIBRARIAN, Role.ADMIN)
        async with self.uow_factory() as uow:
            subjects = await uow.taxonomy.subjects()
            subject = next((s for s in subjects if s.id == subject_id), None)
            if subject is None:
                raise SubjectNotFoundError(params={"subject_id": str(subject_id)})
            doomed = {subject.id} | subject_descendants(subjects, subject.id)
            items = await uow.taxonomy.count_subject_items(doomed)
            topics = await uow.taxonomy.count_subject_topics(doomed)
            if len(doomed) > 1 or items or topics:
                raise SubjectInUseError(
                    params={
                        "children": len(doomed) - 1,
                        "items": items,
                        "topics": topics,
                    }
                )
            await uow.taxonomy.delete_subject(subject.id)
            _audit(uow, actor, TaxonomyAuditType.SUBJECT_DELETE, subject)
            await uow.commit()
