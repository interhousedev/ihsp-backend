"""A group's marks and attendance per student and subject for its curator or head."""

from typing import Any
from uuid import UUID

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.marks.temporary_gpa import with_temporary
from app.modules.academic.application.marks.view_context import (
    build_context,
    caller_locale,
    num,
)
from app.modules.academic.domain.classwork.errors import NotCuratorError
from app.modules.academic.domain.classwork.reports import rate
from app.modules.academic.domain.marks.attendance_merge import combined_source
from app.modules.academic.domain.marks.errors import (
    NotHeadStudentError,
    StudentNotFoundError,
)
from app.modules.academic.domain.marks.read_models import (
    AttendanceCount,
    GroupRoles,
    ResultRow,
)
from app.modules.academic.domain.marks.semesters import (
    resolve_semester,
    semester_window,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.identity import IdentityDirectory

_NO_COUNT = AttendanceCount(absences=0, with_attendance=0)


def _cell(
    subject_id: UUID,
    row: ResultRow | None,
    count: AttendanceCount,
    with_temp: float | None = None,
) -> dict[str, Any]:
    return {
        "subject_id": subject_id,
        "semester_mark": None if row is None else num(row.value),
        "gpa_with_temporary": with_temp,
        "midterm_avg": None if row is None else num(row.midterm_avg),
        "final_avg": None if row is None else num(row.final_avg),
        "lesson_avg": None if row is None else num(row.lesson_avg),
        "emis_rating": None if row is None else row.emis_rating,
        "marks_count": 0 if row is None else row.marks_count,
        "absences": count.absences,
        "lessons": count.with_attendance,
        "absence_rate": rate(count.absences, count.with_attendance),
        "attendance_source": count.source,
    }


class GetGroupProgress:
    """Students x subjects: EMIS results and attendance of one semester (read only).

    Only Administration, the group's curator and the group's head student see it.
    """

    def __init__(
        self, *, uow_factory: MarksUowFactory, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._identity = identity
        self._clock = clock

    async def for_staff(
        self, actor: Actor, group_id: UUID, semester: int | None
    ) -> dict[str, Any]:
        """Return `GroupProgress` for Administration or the group's curator."""
        async with self._uow_factory() as uow:
            group = await uow.reader.group_roles(group_id)
        allowed = actor.has(Role.ADMIN) or (
            group is not None and group.curator_id == actor.user_id
        )
        if group is None or not allowed:
            raise NotCuratorError(params={"group_id": str(group_id)})
        return await self._build(actor, group, semester)

    async def for_head_student(
        self, actor: Actor, semester: int | None
    ) -> dict[str, Any]:
        """Return `GroupProgress` of the caller's group if they are its head."""
        async with self._uow_factory() as uow:
            ctx = await uow.reader.student_context(actor.user_id)
            if ctx is None:
                raise StudentNotFoundError()
            group = await uow.reader.group_roles(ctx.group_id)
        if group is None or group.head_student_id != actor.user_id:
            raise NotHeadStudentError()
        return await self._build(actor, group, semester)

    async def _build(
        self, actor: Actor, group: GroupRoles, semester: int | None
    ) -> dict[str, Any]:
        locale = await caller_locale(self._identity, actor.user_id)
        async with self._uow_factory() as uow:
            reader = uow.reader
            results = {
                sid: await reader.results(sid, None) for sid in group.student_ids
            }
            semesters = sorted({r.semester for rows in results.values() for r in rows})
            sem = resolve_semester(semester, group.current_semester, semesters)
            window = semester_window(
                await reader.terms(),
                group.current_semester,
                sem,
                local_today(self._clock),
            )
            counts: dict[UUID, dict[UUID, AttendanceCount]] = {}
            if window is not None or sem == group.current_semester:
                start, end = window if window is not None else (None, None)
                for sid in group.student_ids:
                    counts[sid] = await reader.attendance_counts(
                        sid, start, end, semester=sem
                    )
            temporary = await with_temporary(
                reader,
                group.student_ids,
                sem,
                (
                    window
                    if window is not None
                    else ((None, None) if sem == group.current_semester else None)
                ),
            )
            subject_ids = {
                r.subject_id
                for rows in results.values()
                for r in rows
                if r.semester == sem and r.subject_id is not None
            }
            subject_ids |= {s for per in counts.values() for s in per}
            view = await build_context(
                reader,
                self._identity,
                locale=locale,
                subject_ids=subject_ids,
                user_ids=group.student_ids,
            )
        subjects = sorted(
            (view.subject_ref(s) for s in subject_ids),
            key=lambda ref: str(ref["name"]).casefold(),
        )
        students: list[dict[str, Any]] = []
        for sid in group.student_ids:
            person = view.person(sid)
            if person is None:
                continue
            rows = {r.subject_id: r for r in results[sid] if r.semester == sem}
            per = counts.get(sid, {})
            absences = sum(c.absences for c in per.values())
            lessons = sum(c.with_attendance for c in per.values())
            gpa = rows.get(None)
            students.append(
                {
                    "student": person,
                    "gpa": None if gpa is None else num(gpa.value),
                    "absences": absences,
                    "lessons": lessons,
                    "absence_rate": rate(absences, lessons),
                    "attendance_source": combined_source(
                        c.source for c in per.values()
                    ),
                    "cells": [
                        _cell(
                            ref["id"],
                            rows.get(ref["id"]),
                            per.get(ref["id"], _NO_COUNT),
                            temporary.get((sid, ref["id"])),
                        )
                        for ref in subjects
                    ],
                }
            )
        students.sort(
            key=lambda s: (
                str(s["student"]["last_name"]).casefold(),
                str(s["student"]["first_name"]).casefold(),
            )
        )
        return {
            "group_id": group.id,
            "group_name": group.name,
            "semester": sem,
            "semesters": sorted(set(semesters) | {sem}),
            "subjects": subjects,
            "students": students,
        }
