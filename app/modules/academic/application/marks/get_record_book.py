"""All semesters with GPA and semester marks (WEB-15)."""

from collections import defaultdict
from typing import Any

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.view_context import (
    build_context,
    caller_locale,
    num,
)
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.modules.academic.domain.marks.read_models import ResultRow
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


class GetRecordBook:
    """Builds `RecordBook` from the stored results of every semester."""

    def __init__(
        self, *, uow_factory: MarksUowFactory, identity: IdentityDirectory
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity

    async def execute(self, actor: Actor) -> dict[str, Any]:
        """Return `RecordBook`."""
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            if await uow.reader.student_context(actor.user_id) is None:
                raise StudentNotFoundError()
            results = await uow.reader.results(actor.user_id, None)
            view = await build_context(
                uow.reader,
                self._identity,
                locale=locale,
                subject_ids={r.subject_id for r in results if r.subject_id},
            )
        by_semester: dict[int, list[ResultRow]] = defaultdict(list)
        for row in results:
            by_semester[row.semester].append(row)
        semesters = []
        for semester in sorted(by_semester):
            rows = by_semester[semester]
            subjects: list[dict[str, Any]] = [
                {
                    "subject": view.subject_ref(r.subject_id),
                    "semester_mark": num(r.value),
                    "emis_rating": r.emis_rating,
                }
                for r in rows
                if r.subject_id is not None
            ]
            subjects.sort(key=lambda s: str(s["subject"]["name"]).casefold())
            gpa = next((r.value for r in rows if r.subject_id is None), None)
            semesters.append(
                {"semester": semester, "gpa": num(gpa), "subjects": subjects}
            )
        return {"semesters": semesters}
