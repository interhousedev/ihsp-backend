"""List students for Administration (ADM-3, ADM-17)."""

from uuid import UUID

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.results import (
    StudentItemData,
    StudentsPage,
)
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.student import Student
from app.shared.contracts.identity import IdentityDirectory, UserRef, UserStatus
from app.shared.pagination import decode_cursor, encode_cursor

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class ListStudents:
    """Search and filter students; names and EMIS status come from identity."""

    def __init__(self, uow_factory: UowFactory, identity: IdentityDirectory) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity

    async def execute(
        self,
        *,
        query: str | None = None,
        group_id: UUID | None = None,
        subgroup: int | None = None,
        status: str | None = None,
        emis_status: str | None = None,
        registered: bool | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> StudentsPage:
        """Return one page ordered by name; filters apply together."""
        async with self.uow_factory() as uow:
            students = await uow.students.list_filtered(
                group_id=group_id, subgroup=subgroup, status=status
            )
            groups = await uow.groups.get_many({s.group_id for s in students})
        users = (
            await self.identity.get_users([s.user_id for s in students])
            if students
            else {}
        )
        rows = [
            _row(student, users[student.user_id], groups.get(student.group_id))
            for student in students
            if student.user_id in users
        ]
        rows = [r for r in rows if _matches(r, query, emis_status, registered)]
        rows.sort(key=_sort_key)
        return _page(rows, cursor, max(1, min(limit, MAX_LIMIT)))


def _row(student: Student, user: UserRef, group: Group | None) -> StudentItemData:
    return StudentItemData(
        user_id=student.user_id,
        login=user.login,
        first_name=user.first_name,
        last_name=user.last_name,
        group_id=group.id if group else None,
        group_name=group.name if group else None,
        subgroup=student.subgroup,
        status=student.status,
        emis_status=user.emis_status,
        registered=user.status != UserStatus.UNREGISTERED,
        synced_at=student.synced_at,
    )


def _matches(
    row: StudentItemData,
    query: str | None,
    emis_status: str | None,
    registered: bool | None,
) -> bool:
    if emis_status is not None and row.emis_status != emis_status:
        return False
    if registered is not None and row.registered != registered:
        return False
    if not query or not query.strip():
        return True
    haystack = f"{row.last_name} {row.first_name} {row.login or ''}".casefold()
    return all(word in haystack for word in query.casefold().split())


def _sort_key(row: StudentItemData) -> list[str]:
    return [row.last_name.casefold(), row.first_name.casefold(), str(row.user_id)]


def _page(rows: list[StudentItemData], cursor: str | None, limit: int) -> StudentsPage:
    after = decode_cursor(cursor)
    if after is not None:
        rows = [r for r in rows if _sort_key(r) > list(after["k"])]
    page = rows[:limit]
    more = len(rows) > limit
    next_cursor = encode_cursor({"k": _sort_key(page[-1])}) if more else None
    return StudentsPage(items=page, next_cursor=next_cursor)
