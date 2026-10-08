"""Confirm a previewed import: create groups and students (UF-ADM-14 step 3)."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.ports.import_store import ImportStore
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.results import ImportResultData
from app.modules.academic.domain.schedule.errors import ImportExpiredError
from app.modules.academic.domain.schedule.group import Group, clean_group_name
from app.modules.academic.domain.schedule.import_rows import RowKind
from app.modules.academic.domain.schedule.student import Student
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityCommands
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft


class ImportConfirm:
    """Apply the stored preview; conflicts and unchanged rows are skipped."""

    def __init__(
        self,
        uow_factory: UowFactory,
        identity_commands: IdentityCommands,
        store: ImportStore,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity_commands = identity_commands
        self.store = store

    async def execute(self, actor: Actor, import_id: UUID) -> ImportResultData:
        """Create missing groups and unregistered students, move changed ones."""
        payload = await self.store.load(import_id)
        if payload is None:
            raise ImportExpiredError()
        rows: list[dict[str, Any]] = payload["rows"]
        created = updated = 0
        async with self.uow_factory() as uow:
            groups: dict[str, Group] = {}
            for row in rows:
                kind = row["kind"]
                if kind not in (RowKind.NEW, RowKind.CHANGED):
                    continue
                group = await self._group(uow, groups, row["group_name"])
                if kind == RowKind.NEW:
                    await self._create_student(uow, group, row)
                    created += 1
                elif await self._move_student(uow, group, row):
                    updated += 1
            uow.audit(
                AuditDraft(
                    type="students.imported",
                    actor_id=actor.user_id,
                    metadata={"created": created, "updated": updated},
                )
            )
            await uow.commit()
        await self.store.delete(import_id)
        return ImportResultData(
            created=created, updated=updated, skipped=len(rows) - created - updated
        )

    @staticmethod
    async def _group(
        uow: ScheduleUnitOfWork, cache: dict[str, Group], name: str
    ) -> Group:
        clean, slug = clean_group_name(name)
        if slug in cache:
            return cache[slug]
        group = await uow.groups.find_active_by_slug(slug)
        if group is None:
            group = Group(id=new_id(), name=clean, slug=slug)
            await uow.groups.add(group)
        cache[slug] = group
        return group

    async def _create_student(
        self, uow: ScheduleUnitOfWork, group: Group, row: dict[str, Any]
    ) -> None:
        user = await self.identity_commands.create_unregistered_student(
            first_name=row["first_name"],
            last_name=row["last_name"],
            middle_name=row["middle_name"],
            emis_student_id=row["emis_student_id"],
        )
        await uow.students.add(Student(user_id=user.id, group_id=group.id))

    @staticmethod
    async def _move_student(
        uow: ScheduleUnitOfWork, group: Group, row: dict[str, Any]
    ) -> bool:
        student = await uow.students.get(UUID(row["user_id"]))
        if student is None:
            return False
        student.move_to(group.id)
        await uow.students.save(student)
        return True
