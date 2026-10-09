"""Import and refresh a group's timetable from EMIS (ACA-1, ACA-4, ACA-5, ACA-7).

Run in the background after a registration and, for each group with students, in the
20:00 sync. One student's EMIS link answers for that student's own half; the other
half arrives when a student of that half syncs. The run is idempotent.
"""

import datetime as dt
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.academic.application.schedule.bootstrap_teachers import (
    TeacherResolver,
)
from app.modules.academic.application.schedule.common import (
    UowFactory,
    kick_recompute_due_dates,
    today,
)
from app.modules.academic.application.schedule.emis_entries import (
    EntryReconciler,
    EntryTally,
)
from app.modules.academic.application.schedule.emis_lessons import (
    LessonReconciler,
    LessonTally,
)
from app.modules.academic.application.schedule.emis_subjects import SubjectResolver
from app.modules.academic.application.schedule.generate_lessons import GenerateLessons
from app.modules.academic.application.schedule.ports.lesson_urls import (
    LessonUrlImporter,
)
from app.modules.academic.application.schedule.ports.room_page_cache import (
    RoomPageCache,
)
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.application.schedule.room_cache import (
    invalidate_room_pages,
)
from app.modules.academic.application.schedule.sync_class_hours import SyncClassHours
from app.modules.academic.domain.schedule.calendar import monday_of
from app.modules.academic.domain.schedule.emis_timetable import derive_slots
from app.modules.academic.domain.schedule.student import Student
from app.modules.academic.domain.schedule.term import Term, pick_current_term
from app.shared.actor import SYSTEM_USER_ID
from app.shared.clock import Clock
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisClass,
    EmisSource,
    EmisUnavailable,
)
from app.shared.contracts.identity import IdentityCommands
from app.shared.notifications import AuditDraft
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

WEEKS = 4  # this week and the next three
TimetableStatus = Literal[
    "synced", "no_term", "no_group", "no_student", "empty", "emis_unavailable"
]


@dataclass(frozen=True, slots=True)
class TimetableResult:
    """How a run ended and what it changed."""

    status: TimetableStatus
    entries: int = 0  # added
    merged: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    teachers: int = 0
    lessons: int = 0  # created, moved, cancelled or generated
    resources: int = 0
    subgroup: int | None = None


class SyncGroupTimetable:
    """Make a group's EMIS entries, lessons and lesson details equal to EMIS."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        emis: EmisSource,
        identity_commands: IdentityCommands,
        sync_class_hours: SyncClassHours,
        generate: GenerateLessons,
        urls: LessonUrlImporter,
        cache: RoomPageCache,
        kicker: TaskKicker,
        clock: Clock,
        import_topics: bool = False,
    ) -> None:
        """Store the dependencies; topics and their files come only with the setting."""
        self.uow_factory = uow_factory
        self.emis = emis
        self.identity_commands = identity_commands
        self.sync_class_hours = sync_class_hours
        self.generate = generate
        self.urls = urls
        self.cache = cache
        self.kicker = kicker
        self.clock = clock
        self.import_topics = import_topics

    async def execute(
        self, *, group_id: UUID, user_id: UUID, refresh_bells: bool = True
    ) -> TimetableResult:
        """Sync the group through the student's EMIS link."""
        day = today(self.clock)
        async with self.uow_factory() as uow:
            term = pick_current_term(await uow.terms.list_all(), day)
        if term is None:
            return TimetableResult("no_term")
        first = monday_of(day)
        last = first + dt.timedelta(days=7 * WEEKS - 1)
        if refresh_bells:
            await self._refresh_bells(user_id)
        classes = await self._fetch(user_id, first, last)
        if classes is None:
            return TimetableResult("emis_unavailable")
        if not classes:
            return TimetableResult("empty")
        teachers = TeacherResolver(self.identity_commands)
        done = await self._entries(
            term, group_id, user_id, classes, (first, last), teachers
        )
        if isinstance(done, TimetableResult):
            return done
        entries, scope, subgroup = done
        generated = await self._generate(term, day, last)
        lessons = await self._lessons(
            term, group_id, classes, scope, (first, last), teachers
        )
        resources = (
            await self.urls.import_lesson_urls(list(lessons.urls.values()))
            if lessons.urls
            else 0
        )
        log.info(
            "emis_group_synced",
            group_id=str(group_id),
            entries=entries.added,
            lessons=lessons.created + lessons.moved + lessons.cancelled,
        )
        return TimetableResult(
            "synced",
            entries=entries.added,
            merged=entries.merged,
            updated=entries.updated,
            removed=entries.removed,
            skipped=entries.skipped,
            teachers=teachers.count,
            lessons=generated + lessons.created + lessons.moved + lessons.cancelled,
            resources=resources,
            subgroup=subgroup,
        )

    # - - - EMIS - - -

    async def _refresh_bells(self, user_id: UUID) -> None:
        """Bells first, so new lessons get the EMIS times (a failure does not stop)."""
        try:
            await self.sync_class_hours.execute(user_id)
        except (EmisAuthFailed, EmisUnavailable):
            log.warning("emis_bells_unavailable", user_id=str(user_id))

    async def _fetch(
        self, user_id: UUID, first: dt.date, last: dt.date
    ) -> list[EmisClass] | None:
        try:
            return await self.emis.timetable(user_id, first, last)
        except (EmisAuthFailed, EmisUnavailable) as exc:
            log.warning("emis_timetable_unavailable", error=exc.support_details)
            return None

    # - - - Entries - - -

    async def _entries(
        self,
        term: Term,
        group_id: UUID,
        user_id: UUID,
        classes: Sequence[EmisClass],
        window: tuple[dt.date, dt.date],
        teachers: TeacherResolver,
    ) -> tuple[EntryTally, set[int | None], int | None] | TimetableResult:
        now = self.clock.now()
        async with self.uow_factory() as uow:
            await uow.lock_term(term.id)
            group = await uow.groups.get(group_id)
            if group is None:
                return TimetableResult("no_group")
            student = await uow.students.get(user_id)
            if student is None or student.group_id != group_id:
                return TimetableResult("no_student")
            subgroup = await self._own_subgroup(uow, student, classes)
            slots = derive_slots(term, classes, window[0], window[1])
            scope: set[int | None] = {None, subgroup}
            scope.update(item.subgroup for item in classes)
            tally = await EntryReconciler(
                uow,
                term=term,
                group=group,
                teachers=teachers,
                subjects=SubjectResolver(uow),
                now=now,
            ).run(slots, scope)
            kick_recompute_due_dates(uow, self.kicker, tally.changed_lessons)
            await invalidate_room_pages(uow, self.cache, tally.room_ids)
            uow.audit(
                AuditDraft(
                    type="group.timetable_synced",
                    metadata={
                        "group_id": str(group.id),
                        "term_id": str(term.id),
                        "added": tally.added,
                        "merged": tally.merged,
                        "updated": tally.updated,
                        "removed": tally.removed,
                        "skipped": tally.skipped,
                        "source": "emis",
                    },
                )
            )
            await uow.commit()
        return tally, scope, subgroup

    async def _own_subgroup(
        self, uow: ScheduleUnitOfWork, student: Student, classes: Sequence[EmisClass]
    ) -> int | None:
        """The student's half; EMIS names it (class by class) when nobody set it."""
        if student.subgroup is not None:
            return student.subgroup
        halves = Counter(item.subgroup for item in classes if item.subgroup)
        if not halves:
            return None
        top = max(halves.values())
        chosen = min(half for half, count in halves.items() if count == top)
        student.assign_subgroup(chosen, by=SYSTEM_USER_ID, now=self.clock.now())
        await uow.students.save(student)
        uow.audit(
            AuditDraft(
                type="subgroup.assigned",
                user_id=student.user_id,
                actor_id=SYSTEM_USER_ID,
                metadata={
                    "group_id": str(student.group_id),
                    "subgroup": chosen,
                    "previous": None,
                    "source": "emis",
                },
            )
        )
        return chosen

    # - - - Lessons - - -

    async def _generate(self, term: Term, day: dt.date, last: dt.date) -> int:
        start = max(day, term.starts_on)
        if start > last:
            return 0
        return await self.generate.execute(
            term_id=term.id, from_date=start, days=(last - start).days + 1
        )

    async def _lessons(
        self,
        term: Term,
        group_id: UUID,
        classes: Sequence[EmisClass],
        scope: set[int | None],
        window: tuple[dt.date, dt.date],
        teachers: TeacherResolver,
    ) -> LessonTally:
        async with self.uow_factory() as uow:
            await uow.lock_term(term.id)
            emis_entries = {
                entry.id
                for entry in await uow.entries.list_for_term(term.id)
                if entry.source == "emis"
            }
            tally = await LessonReconciler(
                uow,
                term=term,
                group_id=group_id,
                teachers=teachers,
                subjects=SubjectResolver(uow),
                emis_entry_ids=emis_entries,
                now=self.clock.now(),
                today=today(self.clock),
                import_topics=self.import_topics,
            ).run(classes, scope, window)
            kick_recompute_due_dates(uow, self.kicker, tally.changed)
            await invalidate_room_pages(uow, self.cache, tally.room_ids)
            await uow.commit()
        return tally
