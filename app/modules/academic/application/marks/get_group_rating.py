"""The head student's group rating by semester GPA (read only, from stored results)."""

from typing import Any

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.view_context import (
    build_context,
    caller_locale,
    num,
)
from app.modules.academic.domain.marks.errors import (
    NotHeadStudentError,
    StudentNotFoundError,
)
from app.modules.academic.domain.marks.semesters import resolve_semester
from app.shared.actor import Actor
from app.shared.contracts.identity import IdentityDirectory


def rank_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order rows by GPA, highest first, and rank them (competition ranking).

    Equal GPAs share a rank (1, 1, 3). A row without a GPA is unranked (rank None)
    and goes last, ordered by name.
    """
    ranked = sorted(
        (r for r in rows if r["gpa"] is not None),
        key=lambda r: (-r["gpa"], r["name"].casefold()),
    )
    place = 0
    previous: float | None = None
    for position, row in enumerate(ranked, start=1):
        if row["gpa"] != previous:
            place = position
            previous = row["gpa"]
        row["rank"] = place
    unranked = sorted(
        (r for r in rows if r["gpa"] is None), key=lambda r: r["name"].casefold()
    )
    for row in unranked:
        row["rank"] = None
    return ranked + unranked


class GetGroupRating:
    """The GPA of every student in the caller's group, ranked (head student only).

    The same rule as the group progress: only the group's head student sees it.
    `emis_rating` is the EMIS rating stored on the semester GPA row; null when none
    was stored. Students without a GPA for the semester are listed unranked.
    """

    def __init__(
        self, *, uow_factory: MarksUowFactory, identity: IdentityDirectory
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity

    async def for_head_student(
        self, actor: Actor, semester: int | None
    ) -> list[dict[str, Any]]:
        """Return the ranked rows of the caller's group for one semester."""
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            reader = uow.reader
            ctx = await reader.student_context(actor.user_id)
            if ctx is None:
                raise StudentNotFoundError()
            group = await reader.group_roles(ctx.group_id)
            if group is None or group.head_student_id != actor.user_id:
                raise NotHeadStudentError()
            results = {
                sid: await reader.results(sid, None) for sid in group.student_ids
            }
            semesters = sorted({r.semester for rows in results.values() for r in rows})
            sem = resolve_semester(semester, group.current_semester, semesters)
            view = await build_context(
                reader,
                self._identity,
                locale=locale,
                subject_ids=set(),
                user_ids=group.student_ids,
            )
        rows: list[dict[str, Any]] = []
        for sid in group.student_ids:
            person = view.person(sid)
            if person is None:
                continue
            gpa = next(
                (r for r in results[sid] if r.semester == sem and r.subject_id is None),
                None,
            )
            rows.append(
                {
                    "name": f"{person['first_name']} {person['last_name']}".strip(),
                    "gpa": None if gpa is None else num(gpa.value),
                    "emis_rating": None if gpa is None else gpa.emis_rating,
                    "rank": None,
                    "is_me": sid == actor.user_id,
                }
            )
        return rank_rows(rows)
