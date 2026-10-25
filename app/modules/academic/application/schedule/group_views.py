"""Building GroupItem and GroupDetail read models."""

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.schedule.common import person_data
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.results import (
    GroupDetailData,
    GroupItemData,
    GroupStudentData,
    PersonData,
)
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.student import Student
from app.shared.contracts.identity import IdentityDirectory, UserRef, UserStatus

UNKNOWN_NAME = "?"


def _is_registered(user: UserRef | None) -> bool:
    return user is not None and user.status != UserStatus.UNREGISTERED


def _person(users: dict[UUID, UserRef], user_id: UUID | None) -> PersonData | None:
    user = users.get(user_id) if user_id else None
    return person_data(user) if user else None


async def _users(
    identity: IdentityDirectory, groups: Sequence[Group], students: Sequence[Student]
) -> dict[UUID, UserRef]:
    ids: set[UUID] = {student.user_id for student in students}
    for group in groups:
        ids.update(i for i in (group.curator_id, group.head_student_id) if i)
    return await identity.get_users(sorted(ids)) if ids else {}


def _item(
    group: Group, students: Sequence[Student], users: dict[UUID, UserRef]
) -> GroupItemData:
    active = [student for student in students if student.status == "active"]
    return GroupItemData(
        id=group.id,
        name=group.name,
        slug=group.slug,
        current_semester=group.current_semester,
        status=group.status,
        students_count=len(active),
        subgroups_assigned=sum(1 for s in active if s.subgroup is not None),
        unregistered_count=sum(
            1 for s in active if not _is_registered(users.get(s.user_id))
        ),
        curator=_person(users, group.curator_id),
        head_student=_person(users, group.head_student_id),
    )


async def build_group_items(
    uow: ScheduleUnitOfWork, identity: IdentityDirectory, groups: Sequence[Group]
) -> list[GroupItemData]:
    """Return list rows with counts for the groups."""
    if not groups:
        return []
    wanted = {group.id for group in groups}
    by_group: dict[UUID, list[Student]] = defaultdict(list)
    for student in await uow.students.list_filtered(status="active"):
        if student.group_id in wanted:
            by_group[student.group_id].append(student)
    everyone = [student for rows in by_group.values() for student in rows]
    users = await _users(identity, groups, everyone)
    return [_item(group, by_group[group.id], users) for group in groups]


async def build_group_detail(
    uow: ScheduleUnitOfWork, identity: IdentityDirectory, group: Group
) -> GroupDetailData:
    """Return the group with every student (active and left) and the counts."""
    students = await uow.students.list_filtered(group_id=group.id)
    users = await _users(identity, [group], students)
    item = _item(group, students, users)
    rows = [_student_row(student, users.get(student.user_id)) for student in students]
    rows.sort(key=lambda r: (r.last_name.casefold(), r.first_name.casefold()))
    return GroupDetailData(
        id=item.id,
        name=item.name,
        slug=item.slug,
        current_semester=item.current_semester,
        status=item.status,
        students_count=item.students_count,
        subgroups_assigned=item.subgroups_assigned,
        unregistered_count=item.unregistered_count,
        curator=item.curator,
        head_student=item.head_student,
        emis_group_id=group.emis_group_id,
        students=rows,
    )


def _student_row(student: Student, user: UserRef | None) -> GroupStudentData:
    return GroupStudentData(
        user_id=student.user_id,
        first_name=user.first_name if user else UNKNOWN_NAME,
        last_name=user.last_name if user else UNKNOWN_NAME,
        subgroup=student.subgroup,
        status=student.status,
        registered=_is_registered(user),
    )
