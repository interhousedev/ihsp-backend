"""Use case: the curator's list of the group's students (STF-11, STF-14)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.lookup import ensure_curator
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)
from app.modules.academic.domain.classwork.reports import rate, student_flags
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.identity import IdentityDirectory, UserStatus


class CuratorStudents:
    """Students with subgroup, absence rate, GPA and the reasons to look at them."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        identity: IdentityDirectory,
        schedule: ScheduleQueries,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity
        self.schedule = schedule

    async def execute(self, actor: Actor, group_id: UUID) -> list[dict[str, Any]]:
        """Return ``CuratorStudent`` JSON items, flagged students first."""
        await ensure_curator(self.schedule, actor, group_id)
        now, today = self.clock.now(), local_today(self.clock)
        async with self.uow_factory() as uow:
            students = await uow.students.active_in_groups([group_id])
            term = await uow.results.current_term(today)
            rows = []
            if term is not None:
                rows = await uow.reports.group_report(
                    group_id, "student", term.starts_on, term.ends_on, now
                )
            semester = students[0].current_semester if students else None
            ids = [student.user_id for student in students]
            gpas = await uow.results.gpas(ids, semester) if semester else {}
            before = (
                await uow.results.gpas(ids, semester - 1)
                if semester and semester > 1
                else {}
            )
        users = await self.identity.get_users(ids)
        rates = {row.key: rate(row.absences, row.lessons) for row in rows}
        items: list[dict[str, Any]] = []
        for student in students:
            user = users.get(student.user_id)
            absence_rate = rates.get(str(student.user_id))
            gpa = gpas.get(student.user_id)
            flags = student_flags(
                absence_rate, gpa, before.get(student.user_id), student.subgroup
            )
            items.append(
                {
                    "user_id": str(student.user_id),
                    "first_name": user.first_name if user else "",
                    "last_name": user.last_name if user else "",
                    "subgroup": student.subgroup,
                    "status": student.status,
                    "registered": user is not None
                    and user.status != UserStatus.UNREGISTERED,
                    "absence_rate": absence_rate,
                    "gpa": gpa,
                    "flags": flags,
                }
            )
        items.sort(key=lambda i: (-len(i["flags"]), i["last_name"], i["first_name"]))
        return items
