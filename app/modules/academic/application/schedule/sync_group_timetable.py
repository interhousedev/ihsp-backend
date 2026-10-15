"""Import and refresh a group's timetable from EMIS (ACA-1, ACA-4, ACA-5, ACA-7).

Run in the background after a registration and, for each group with students, in the
20:00 sync. One student's EMIS link answers for that student's own half; the other
half arrives when a student of that half syncs. The run is idempotent.
"""

import asyncio
import datetime as dt
from collections import Counter
from collections.abc import Collection, Sequence
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
    LessonMaterialImporter,
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
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.calendar import monday_of
from app.modules.academic.domain.schedule.emis_timetable import derive_slots
from app.modules.academic.domain.schedule.material_scope import MaterialScope
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
from app.shared.jobs import job_should_stop
from app.shared.notifications import AuditDraft
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

WEEKS = 4  # this week and the next three
ONE_DAY = dt.timedelta(days=1)
FETCH_DAYS = 56  # one gateway call covers at most 62 days
WEEKS_SPAN = dt.timedelta(days=7 * WEEKS - 1)
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
        urls: LessonMaterialImporter,
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
        self,
        *,
        group_id: UUID,
        user_id: UUID,
        refresh_bells: bool = True,
        full_term: bool = False,
    ) -> TimetableResult:
        """Sync the group through the student's EMIS link.

        On the first sync of a group (``full_term``, or no lesson before this week)
        the materials of the term's earlier weeks are imported too.
        """
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
        backfilled = await self._backfill(term, group_id, first)
        generated = await self._generate(term, day, last)
        lessons = await self._lessons(
            term, group_id, classes, scope, (first, last), teachers
        )
        resources = (
            await self.urls.import_materials(user_id, list(lessons.urls.values()))
            if lessons.urls
            else 0
        )
        if self.import_topics and (full_term or backfilled):
            earlier = await self._materials_between(
                term, group_id, user_id, (term.starts_on, first - ONE_DAY)
            )
            resources += earlier or 0
        log.info(
            "emis_group_synced",
            group_id=str(group_id),
            entries=entries.added,
            backfilled=backfilled,
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
            lessons=(
                backfilled
                + generated
                + lessons.created
                + lessons.moved
                + lessons.cancelled
            ),
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
        """Lessons from today (or the term's start) on, inside the term."""
        return await self._generate_within(
            term, max(day, term.starts_on), min(last, term.ends_on)
        )

    async def _backfill(self, term: Term, group_id: UUID, first: dt.date) -> int:
        """Lessons for the term's weeks before this sync, if the group has none there.

        Only a group with no lesson at all before ``first`` is filled, so real EMIS
        data and earlier runs are never duplicated or overwritten.
        """
        end = min(first - ONE_DAY, term.ends_on)
        if term.starts_on > end:
            return 0
        keys = audience_keys.student_keys(group_id, None)
        async with self.uow_factory() as uow:
            found = await uow.lessons.in_audience(term.id, term.starts_on, end, keys)
        if found:
            return 0
        return await self._generate_within(term, term.starts_on, end, keys)

    async def _generate_within(
        self,
        term: Term,
        start: dt.date,
        end: dt.date,
        audience: list[str] | None = None,
    ) -> int:
        if start > end:
            return 0
        return await self.generate.execute(
            term_id=term.id,
            from_date=start,
            days=(end - start).days + 1,
            audience=audience,
        )

    async def _lessons(
        self,
        term: Term,
        group_id: UUID,
        classes: Sequence[EmisClass],
        scope: set[int | None],
        window: tuple[dt.date, dt.date],
        teachers: TeacherResolver,
        *,
        import_topics: bool | None = None,
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
                import_topics=(
                    self.import_topics if import_topics is None else import_topics
                ),
            ).run(classes, scope, window)
            kick_recompute_due_dates(uow, self.kicker, tally.changed)
            await invalidate_room_pages(uow, self.cache, tally.room_ids)
            await uow.commit()
        return tally

    # - - - Materials of a whole term (first sync, admin re-sync) - - -

    async def resync_materials(
        self,
        *,
        group_id: UUID,
        terms: Collection[tuple[str, int]] | None,
        fetchers: Sequence[Sequence[UUID]],
        scope: MaterialScope | None = None,
    ) -> int:
        """Replace the group's EMIS materials in the chosen terms; return how many.

        ``terms`` are (academic year, half) pairs, None for the current term;
        ``fetchers`` are at most two lists of students (one per half of a split
        group), each tried in order until one EMIS link answers. Nothing is deleted
        when no student could be read. With a ``scope`` only the lessons of its
        subject (and teacher) are touched, and a soft scope deletes nothing.
        """
        day = today(self.clock)
        total = 0
        for term in await self._started_terms(terms, day):
            if await job_should_stop():
                break  # never purge a term that would not be imported again
            total += await self._resync_term(term, day, group_id, fetchers, scope)
        return total

    async def _resync_term(
        self,
        term: Term,
        day: dt.date,
        group_id: UUID,
        fetchers: Sequence[Sequence[UUID]],
        scope: MaterialScope | None,
    ) -> int:
        """Purge and re-import one term's materials; 0 when EMIS is not asked."""
        window = (term.starts_on, min(term.ends_on, monday_of(day) + WEEKS_SPAN))
        skip = await self._kept(term, group_id, window, scope)
        if skip is None:
            return 0  # the group has no lesson in the scope: EMIS is not asked
        fetched = await self._fetch_slots(fetchers, window)
        if not fetched:
            log.warning("emis_materials_resync_unread", group_id=str(group_id))
            return 0
        await self._purge_scoped(term, group_id, window, scope)
        total = 0
        for user_id, classes in fetched:
            total += await self._apply_materials(
                term, group_id, user_id, classes, window, only=scope, skip=skip
            )
        return total

    async def _fetch_slots(
        self, fetchers: Sequence[Sequence[UUID]], window: tuple[dt.date, dt.date]
    ) -> list[tuple[UUID, list[EmisClass]]]:
        """The first answering student of each slot (slots nobody answers drop)."""
        return [
            found
            for slot in fetchers
            if (found := await self._first_answer(slot, window)) is not None
        ]

    async def _kept(
        self,
        term: Term,
        group_id: UUID,
        window: tuple[dt.date, dt.date],
        scope: MaterialScope | None,
    ) -> set[UUID] | None:
        """Lessons a soft pull leaves alone; None when the scope has no lesson."""
        if scope is None:
            return set()
        touched = await self._scoped(term, group_id, window, scope)
        if not touched:
            return None
        if not scope.soft:
            return set()
        return await self.urls.lessons_with_materials(touched)

    async def _purge_scoped(
        self,
        term: Term,
        group_id: UUID,
        window: tuple[dt.date, dt.date],
        scope: MaterialScope | None,
    ) -> None:
        """Everything without a scope, its lessons for a full one, nothing if soft."""
        if scope is None:
            await self._purge(term, group_id, window)
        elif not scope.soft:
            lessons = await self._scoped(term, group_id, window, scope)
            purged = await self.urls.purge(lessons)
            log.info("emis_materials_purged", group_id=str(group_id), resources=purged)

    async def _started_terms(
        self, terms: Collection[tuple[str, int]] | None, day: dt.date
    ) -> list[Term]:
        """The chosen terms (None: the current one) that have begun."""
        async with self.uow_factory() as uow:
            every = await uow.terms.list_all()
        if terms is None:
            current = pick_current_term(every, day)
            every = [current] if current else []
        else:
            every = [t for t in every if (t.academic_year, t.half) in terms]
        return [term for term in every if term.starts_on <= day]

    async def _scoped(
        self,
        term: Term,
        group_id: UUID,
        window: tuple[dt.date, dt.date],
        scope: MaterialScope,
    ) -> list[UUID]:
        """The group's lessons in the window that the scope touches."""
        keys = audience_keys.student_keys(group_id, None)
        async with self.uow_factory() as uow:
            lessons = await uow.lessons.in_audience(term.id, *window, keys)
        return [lesson.id for lesson in lessons if scope.matches(lesson)]

    async def _first_answer(
        self, slot: Sequence[UUID], window: tuple[dt.date, dt.date]
    ) -> tuple[UUID, list[EmisClass]] | None:
        for user_id in slot:
            classes = await self._fetch_span(user_id, window)
            if classes is not None:
                return user_id, classes
        return None

    async def _purge(
        self, term: Term, group_id: UUID, window: tuple[dt.date, dt.date]
    ) -> None:
        keys = audience_keys.student_keys(group_id, None)
        async with self.uow_factory() as uow:
            lessons = await uow.lessons.in_audience(term.id, *window, keys)
        purged = await self.urls.purge([lesson.id for lesson in lessons])
        log.info("emis_materials_purged", group_id=str(group_id), resources=purged)

    async def _materials_between(
        self,
        term: Term,
        group_id: UUID,
        user_id: UUID,
        window: tuple[dt.date, dt.date],
    ) -> int | None:
        """Import the materials of the classes dated in the window (None: no EMIS)."""
        window = (max(window[0], term.starts_on), min(window[1], term.ends_on))
        if window[0] > window[1]:
            return 0
        classes = await self._fetch_span(user_id, window)
        if classes is None:
            return None
        return await self._apply_materials(term, group_id, user_id, classes, window)

    async def _apply_materials(
        self,
        term: Term,
        group_id: UUID,
        user_id: UUID,
        classes: Sequence[EmisClass],
        window: tuple[dt.date, dt.date],
        *,
        only: MaterialScope | None = None,
        skip: Collection[UUID] = (),
    ) -> int:
        async with self.uow_factory() as uow:
            student = await uow.students.get(user_id)
        scope: set[int | None] = {None, student.subgroup if student else None}
        scope.update(item.subgroup for item in classes)
        teachers = TeacherResolver(self.identity_commands)
        tally = await self._lessons(
            term, group_id, classes, scope, window, teachers, import_topics=True
        )
        items = list(tally.urls.values())
        if only is not None:
            allowed = set(await self._scoped(term, group_id, window, only))
            allowed.difference_update(skip)
            items = [item for item in items if item.lesson_id in allowed]
        if not items:
            return 0
        return await self.urls.import_materials(user_id, items)

    async def _fetch_span(
        self, user_id: UUID, window: tuple[dt.date, dt.date]
    ) -> list[EmisClass] | None:
        """The classes of a long window, asked in spans the gateway accepts.

        The spans are asked in parallel (a term is two or three of them); the
        classes keep the order of the spans.
        """
        spans: list[tuple[dt.date, dt.date]] = []
        first = window[0]
        while first <= window[1]:
            last = min(first + dt.timedelta(days=FETCH_DAYS - 1), window[1])
            spans.append((first, last))
            first = last + ONE_DAY
        parts = await asyncio.gather(
            *(self._fetch(user_id, first, last) for first, last in spans)
        )
        classes: list[EmisClass] = []
        for part in parts:
            if part is None:
                return None
            classes.extend(part)
        return classes
