"""All semesters with GPA and semester marks (WEB-15)."""

from collections import defaultdict
from typing import Any
from uuid import UUID

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.semester_range import semester_range
from app.modules.academic.application.marks.temporary_gpa import (
    with_temporary,
)
from app.modules.academic.application.marks.view_context import (
    build_context,
    caller_locale,
    num,
)
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.modules.academic.domain.marks.read_models import ResultRow
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory


class GetRecordBook:
    """Builds `RecordBook` from the stored results of every semester."""

    def __init__(
        self,
        *,
        uow_factory: MarksUowFactory,
        identity: IdentityDirectory,
        clock: Clock,
    ) -> None:
        """Store collaborators."""
        self._clock = clock
        self._uow_factory = uow_factory
        self._identity = identity

    async def execute(self, actor: Actor) -> dict[str, Any]:
        """Return `RecordBook`."""
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            ctx = await uow.reader.student_context(actor.user_id)
            if ctx is None:
                raise StudentNotFoundError()
            results = await uow.reader.results(actor.user_id, None)
            temporary: dict[tuple[int, UUID], float] = {}
            today = local_today(self._clock)
            for sem in sorted({r.semester for r in results}):
                window = await semester_range(uow.reader, ctx, sem, today)
                found = await with_temporary(uow.reader, [ctx.user_id], sem, window)
                for (_sid, subject), value in found.items():
                    temporary[(sem, subject)] = value
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
                    "gpa_with_temporary": temporary.get((semester, r.subject_id)),
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
