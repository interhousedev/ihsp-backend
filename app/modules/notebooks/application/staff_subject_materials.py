"""Use cases: a teacher's materials of a subject (all their groups, or one)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.notebooks.application.material_target import (
    DefaultMaterialDraft,
    check_target,
)
from app.modules.notebooks.application.teaching_directory import (
    TeachingDirectory,
    TeachingSubject,
)
from app.modules.notebooks.domain.default_materials import (
    DEFAULT_MATERIAL_TITLE_MAX_CHARS,
    MAX_DEFAULT_MATERIALS,
    DefaultMaterial,
    MaterialScope,
)
from app.modules.notebooks.domain.errors import (
    DefaultMaterialExistsError,
    DefaultMaterialInvalidError,
    DefaultMaterialLimitError,
    DefaultMaterialNotFoundError,
    SubjectNotTaughtError,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class SubjectMaterialsView:
    """The three tiers of a subject for a teacher."""

    subject: TeachingSubject
    admin: list[DefaultMaterial]  # read-only
    mine: list[DefaultMaterial]  # for all the teacher's groups of the subject
    groups: list[DefaultMaterial]  # for one group (or subgroup) each


class StaffSubjectMaterials:
    """Lists, adds and removes the materials a teacher keeps for a subject.

    A teacher may only touch a subject (and a group) they teach this term; the
    materials of the administration are read-only to them.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        teaching: TeachingDirectory,
        files: FilesApi | None,
    ) -> None:
        """Store the collaborators (`files` None: file materials are refused)."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.teaching = teaching
        self.files = files

    async def subjects(self, actor: Actor) -> list[TeachingSubject]:
        """The subjects the teacher teaches this term, with their groups."""
        return await self.teaching.subjects(actor.user_id)

    async def overview(self, actor: Actor, subject_id: UUID) -> SubjectMaterialsView:
        """The administration, own and per-group materials of one subject.

        Raises:
            SubjectNotTaughtError: The teacher does not teach the subject.
        """
        subject = await self._subject(actor, subject_id)
        if subject.edu_subject_id is None:
            return SubjectMaterialsView(subject, [], [], [])
        async with self.uow_factory() as uow:
            admin = await uow.default_materials.list_for_subject(subject.edu_subject_id)
            own = await uow.default_materials.list_for_teacher(
                subject.edu_subject_id, actor.user_id
            )
        return SubjectMaterialsView(
            subject,
            admin,
            [x for x in own if x.scope is MaterialScope.TEACHER_SUBJECT],
            [x for x in own if x.scope is MaterialScope.GROUP],
        )

    async def add(
        self,
        actor: Actor,
        subject_id: UUID,
        draft: DefaultMaterialDraft,
        *,
        group_id: UUID | None = None,
        subgroup: int | None = None,
    ) -> DefaultMaterial:
        """Store a material for all the teacher's groups, or for one group.

        Raises:
            SubjectNotTaughtError: The teacher does not teach the subject (or group).
            DefaultMaterialInvalidError: The file, link or item cannot be used.
            DefaultMaterialExistsError: This target is there already.
            DefaultMaterialLimitError: The list is full.
        """
        subject = await self._subject(actor, subject_id)
        if group_id is None:
            subgroup = None
        elif not subject.teaches(group_id, subgroup):
            raise SubjectNotTaughtError()
        if subject.edu_subject_id is None:
            raise DefaultMaterialInvalidError(params={"field": "subject_id"})
        title = draft.title.strip()[:DEFAULT_MATERIAL_TITLE_MAX_CHARS]
        if not title:
            raise DefaultMaterialInvalidError(params={"field": "title"})
        url, file_id, item_id = await check_target(self.files, actor, draft)
        scope = (
            MaterialScope.TEACHER_SUBJECT if group_id is None else MaterialScope.GROUP
        )
        async with self.uow_factory() as uow:
            current = [
                x
                for x in await uow.default_materials.list_for_teacher(
                    subject.edu_subject_id, actor.user_id
                )
                if (x.scope, x.group_id, x.subgroup) == (scope, group_id, subgroup)
            ]
            if len(current) >= MAX_DEFAULT_MATERIALS:
                raise DefaultMaterialLimitError(params={"limit": MAX_DEFAULT_MATERIALS})
            material = DefaultMaterial(
                id=new_id(),
                edu_subject_id=subject.edu_subject_id,
                kind=draft.kind,
                title=title,
                position=max((x.position for x in current), default=-1) + 1,
                created_by=actor.user_id,
                created_at=self.clock.now(),
                file_id=file_id,
                url=url,
                library_item_id=item_id,
                scope=scope,
                teacher_id=actor.user_id,
                group_id=group_id,
                subgroup=subgroup,
            )
            if any(material.same_target(other) for other in current):
                raise DefaultMaterialExistsError()
            await uow.default_materials.add(material)
            await uow.commit()
        return material

    async def remove(self, actor: Actor, subject_id: UUID, material_id: UUID) -> None:
        """Delete one of the teacher's own materials of the subject.

        Raises:
            SubjectNotTaughtError: The teacher does not teach the subject.
            DefaultMaterialNotFoundError: Not theirs, or not of this subject.
        """
        subject = await self._subject(actor, subject_id)
        async with self.uow_factory() as uow:
            material = await uow.default_materials.get(material_id)
            if (
                material is None
                or material.scope is MaterialScope.ADMIN
                or material.teacher_id != actor.user_id
                or material.edu_subject_id != subject.edu_subject_id
            ):
                raise DefaultMaterialNotFoundError()
            await uow.default_materials.delete(material_id)
            await uow.commit()

    async def _subject(self, actor: Actor, subject_id: UUID) -> TeachingSubject:
        subject = await self.teaching.subject(actor.user_id, subject_id)
        if subject is None:
            raise SubjectNotTaughtError()
        return subject
