"""Preview a CSV import of students (UF-ADM-14, ACA-18)."""

from typing import Any

from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.ports.import_store import ImportStore
from app.modules.academic.application.schedule.results import (
    ImportPreviewData,
    ImportRowData,
)
from app.modules.academic.domain.schedule.errors import ImportInvalidError
from app.modules.academic.domain.schedule.import_rows import (
    ClassifiedRow,
    KnownStudent,
    RowKind,
    classify_rows,
    parse_csv,
)
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id


def row_data(item: ClassifiedRow) -> ImportRowData:
    """Map a classified row to ImportRow."""
    row = item.row
    return ImportRowData(
        line=row.line,
        last_name=row.last_name,
        first_name=row.first_name,
        middle_name=row.middle_name,
        group_name=row.group_name,
        emis_student_id=row.emis_student_id,
        note=item.note,
    )


def stored_row(item: ClassifiedRow) -> dict[str, Any]:
    """Serialize a classified row for the import store."""
    row = item.row
    return {
        "kind": item.kind.value,
        "user_id": str(item.user_id) if item.user_id else None,
        "line": row.line,
        "last_name": row.last_name,
        "first_name": row.first_name,
        "middle_name": row.middle_name,
        "group_name": row.group_name,
        "emis_student_id": row.emis_student_id,
        "note": item.note,
    }


class ImportPreview:
    """Parse the file, classify its rows and keep the result for an hour."""

    def __init__(
        self,
        uow_factory: UowFactory,
        identity: IdentityDirectory,
        store: ImportStore,
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.identity = identity
        self.store = store

    async def execute(self, csv_bytes: bytes) -> ImportPreviewData:
        """Return new, changed, unchanged and conflicting rows."""
        rows = parse_csv(csv_bytes)
        if not rows:
            raise ImportInvalidError(params={"reason": "empty"})
        known = await self._known_students()
        classified = classify_rows(rows, known)
        import_id = new_id()
        await self.store.save(import_id, {"rows": [stored_row(c) for c in classified]})
        return ImportPreviewData(
            import_id=import_id,
            new=[row_data(c) for c in classified if c.kind == RowKind.NEW],
            changed=[row_data(c) for c in classified if c.kind == RowKind.CHANGED],
            unchanged=sum(1 for c in classified if c.kind == RowKind.UNCHANGED),
            conflicts=[row_data(c) for c in classified if c.kind == RowKind.CONFLICT],
        )

    async def _known_students(self) -> list[KnownStudent]:
        async with self.uow_factory() as uow:
            students = await uow.students.list_filtered(status="active")
            groups = await uow.groups.get_many({s.group_id for s in students})
        users = (
            await self.identity.get_users([s.user_id for s in students])
            if students
            else {}
        )
        return [
            KnownStudent(
                user_id=student.user_id,
                group_name=groups[student.group_id].name,
                first_name=users[student.user_id].first_name,
                last_name=users[student.user_id].last_name,
                middle_name=users[student.user_id].middle_name,
            )
            for student in students
            if student.user_id in users and student.group_id in groups
        ]
