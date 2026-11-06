"""Apply the dated classes EMIS sends to the lessons of one group (ACA-7).

The weekly entries (``emis_entries``) and the lesson generator make the lessons; this
step lines them up with what EMIS lists on each date:

* a lesson gets the class's kind and the EMIS class id; with ``import_topics`` it also
  gets, until a teacher writes their own, the EMIS topic, and the topic's files and
  video become resources (EMIS fills these in badly, so the setting is off by default);
* a class with no lesson is a moved class (the lesson that holds its id follows it) or
  an added one (a new lesson, from today on);
* a lesson EMIS confirmed before and no longer lists is cancelled; a class EMIS still
  lists, at any pair, is never cancelled, and one that returns is revived.

Lessons changed by hand (``is_overridden`` without an EMIS class id) and lessons of
hand-made entries only get the details; their time, room and status stay as they are.
"""

import datetime as dt
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.academic.application.schedule.bootstrap_teachers import (
    TeacherResolver,
)
from app.modules.academic.application.schedule.emis_subjects import SubjectResolver
from app.modules.academic.application.schedule.ensure_room import ensure_room_in
from app.modules.academic.application.schedule.ports.lesson_urls import (
    EmisMaterial,
    MaterialKind,
)
from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.calendar import (
    bell_for,
    bell_or_nearest,
    lesson_times,
)
from app.modules.academic.domain.schedule.emis_timetable import class_weekday
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.lesson_changes import (
    merge_changes,
    time_label,
)
from app.modules.academic.domain.schedule.term import Term
from app.shared.contracts.emis import EmisClass
from app.shared.ids import new_id

import structlog

log = structlog.get_logger(__name__)

SlotKey = tuple[dt.date, int, str]  # date, period, audience key


@dataclass(slots=True)
class LessonTally:
    """What a reconciliation did with the lessons."""

    enriched: int = 0
    created: int = 0
    moved: int = 0
    cancelled: int = 0
    revived: int = 0
    skipped: int = 0
    changed: list[UUID] = field(default_factory=list)
    room_ids: set[UUID | None] = field(default_factory=set)
    urls: dict[tuple[UUID, str], EmisMaterial] = field(default_factory=dict)


class LessonReconciler:
    """Lines the lessons of a group up with its EMIS classes inside a transaction."""

    def __init__(
        self,
        uow: ScheduleUnitOfWork,
        *,
        term: Term,
        group_id: UUID,
        teachers: TeacherResolver,
        subjects: SubjectResolver,
        emis_entry_ids: Collection[UUID],
        now: dt.datetime,
        today: dt.date,
        import_topics: bool = False,
    ) -> None:
        """Bind to the transaction, the term and the group."""
        self._uow = uow
        self._term = term
        self._group_id = group_id
        self._teachers = teachers
        self._subjects = subjects
        self._emis_entries = set(emis_entry_ids)
        self._now = now
        self._today = today
        self._import_topics = import_topics
        self._tally = LessonTally()
        self._seen: set[int] = set()
        self._matched: set[UUID] = set()
        self._superseded: set[UUID] = set()

    async def run(
        self,
        classes: Sequence[EmisClass],
        scope: Collection[int | None],
        window: tuple[dt.date, dt.date],
    ) -> LessonTally:
        """Reconcile the lessons dated within ``window`` for the halves in ``scope``."""
        keys = {audience_keys.key(self._group_id, half) for half in scope}
        self._seen = {item.class_id for item in classes}
        lessons = await self._uow.lessons.in_audience(
            self._term.id, window[0], window[1], keys
        )
        by_slot = _by_slot(lessons, keys)
        holders = {
            lesson.emis_class_id: lesson
            for lesson in await self._uow.lessons.with_emis_class_ids(self._seen)
            if lesson.emis_class_id is not None
        }
        for item in classes:
            if not self._term.starts_on <= item.date <= self._term.ends_on:
                continue
            key = audience_keys.key(self._group_id, item.subgroup)
            lesson = by_slot.get((item.date, item.pair_number + 1, key))
            holder = holders.get(item.class_id)
            if lesson is not None and holder is not None and holder.id != lesson.id:
                lesson = await self._settle_two(lesson, holder, keys)
            if lesson is not None and self._holds_another_class(lesson, item):
                lesson = None  # that class has moved away; this one is not it
            if lesson is None:
                lesson = await self._moved_or_added(item, key, holders)
            if lesson is not None:
                self._matched.add(lesson.id)
                await self._enrich(lesson, item, keys)
        await self._cancel_missing(lessons, keys)
        return self._tally

    # - - - Finding or making the lesson of a class - - -

    def _holds_another_class(self, lesson: Lesson, item: EmisClass) -> bool:
        """True for a future lesson of a class EMIS now lists somewhere else."""
        return (
            lesson.emis_class_id in self._seen
            and lesson.emis_class_id != item.class_id
            and lesson.id not in self._matched
            and lesson.starts_after(self._now)
            and self._managed(lesson)
        )

    async def _settle_two(
        self, at_slot: Lesson, holder: Lesson, keys: set[str]
    ) -> Lesson | None:
        """The slot has a lesson while another one holds the class: leave one lesson.

        The generator made the slot's lesson for the class's new weekly place. The
        holder has the homework and attendance, so it stays and takes over the slot's
        identity; with content on both sides the old one is a real leftover.
        Returns the lesson at the slot, or None when the holder should move there.
        """
        movable = (
            holder.id not in self._matched
            and self._managed(holder)
            and holder.starts_after(self._now)
            and set(holder.audience) <= keys
        )
        fresh = (
            at_slot.id not in self._matched
            and self._managed(at_slot)
            and at_slot.emis_class_id not in self._seen
        )
        if not movable or not fresh:
            return at_slot
        if at_slot.has_content:
            if holder.has_content:
                self._superseded.add(holder.id)
            else:
                await self._uow.lessons.delete_many([holder.id])
                self._matched.add(holder.id)
                self._note(holder)
            return at_slot
        await self._uow.lessons.delete_many([at_slot.id])
        self._matched.add(at_slot.id)
        self._note(at_slot)
        holder.timetable_entry_id = at_slot.timetable_entry_id
        holder.origin_date = at_slot.origin_date
        return None

    async def _moved_or_added(
        self, item: EmisClass, key: str, holders: dict[int, Lesson]
    ) -> Lesson | None:
        holder = holders.get(item.class_id)
        if holder is not None and holder.id not in self._matched:
            return await self._move(holder, item)
        if item.date < self._today:
            return None  # no lessons are made for days that are over
        return await self._create(item, key)

    def _slot_times(
        self, item: EmisClass
    ) -> tuple[int, dt.datetime, dt.datetime] | None:
        weekday = class_weekday(item.date, self._term)
        period = item.pair_number + 1
        bell = bell_or_nearest(self._term, period, weekday) if weekday else None
        if bell is None:
            log.warning("emis_class_without_bell", class_id=item.class_id)
            self._tally.skipped += 1
            return None
        if weekday and bell_for(self._term, period, weekday) is None:
            log.warning(
                "emis_class_bell_borrowed",
                class_id=item.class_id,
                period=period,
                weekday=weekday,
            )
        starts_at, ends_at = lesson_times(item.date, bell[0], bell[1])
        return item.pair_number + 1, starts_at, ends_at

    async def _move(self, lesson: Lesson, item: EmisClass) -> Lesson | None:
        """Follow a class EMIS moved to another date or pair; keep what it holds."""
        if not self._managed(lesson) or not lesson.starts_after(self._now):
            return None
        slot = self._slot_times(item)
        if slot is None:
            return None
        period, starts_at, ends_at = slot
        changes: dict[str, list[object]] = {}
        if lesson.date != item.date:
            changes["date"] = [lesson.date.isoformat(), item.date.isoformat()]
        if (lesson.starts_at, lesson.ends_at) != (starts_at, ends_at):
            changes["time"] = [
                time_label(lesson.starts_at, lesson.ends_at),
                time_label(starts_at, ends_at),
            ]
        lesson.date, lesson.period = item.date, period
        lesson.starts_at, lesson.ends_at = starts_at, ends_at
        lesson.status = "scheduled"
        lesson.changes = merge_changes(lesson.changes, changes)
        if lesson.changes:
            lesson.changes.pop("status", None)  # any EMIS cancellation is over
        lesson.is_overridden = True
        if not await self._uow.lessons.try_save(lesson):
            log.warning("emis_lesson_move_skipped", lesson_id=str(lesson.id))
            self._tally.skipped += 1
            return None
        self._tally.moved += 1
        self._note(lesson)
        return lesson

    async def _create(self, item: EmisClass, key: str) -> Lesson | None:
        slot = self._slot_times(item)
        if slot is None:
            return None
        period, starts_at, ends_at = slot
        subject = await self._subjects.resolve(
            item.subject, divided=item.subgroup is not None
        )
        teacher_id = await self._teachers.resolve(item.teacher)
        room_id = await self._room(item.room)
        joined = await self._join(item, key, subject.id, teacher_id, room_id, period)
        if joined is not None:
            return joined
        lesson = Lesson(
            id=new_id(),
            term_id=self._term.id,
            date=item.date,
            period=period,
            starts_at=starts_at,
            ends_at=ends_at,
            subject_id=subject.id,
            teacher_id=teacher_id,
            room_id=room_id,
            audience=[key],
            kind=item.kind,
            emis_class_id=item.class_id,
        )
        if not await self._uow.lessons.try_add(lesson):
            log.warning("emis_lesson_skipped", class_id=item.class_id)
            self._tally.skipped += 1
            return None
        self._tally.created += 1
        self._note(lesson)
        return lesson

    async def _join(
        self,
        item: EmisClass,
        key: str,
        subject_id: UUID,
        teacher_id: UUID | None,
        room_id: UUID | None,
        period: int,
    ) -> Lesson | None:
        """One lesson taught to several groups: join the one that is already there."""
        if teacher_id is None:
            return None
        slot = self._slot_times(item)
        assert slot is not None
        for other in await self._uow.lessons.find_overlapping(slot[1], slot[2]):
            same = (other.date, other.period, other.subject_id, other.teacher_id) == (
                item.date,
                period,
                subject_id,
                teacher_id,
            )
            if same and other.room_id == room_id and key not in other.audience:
                other.audience = [*other.audience, key]
                await self._uow.lessons.save(other)
                self._note(other)
                return other
        return None

    async def _room(self, name: str | None) -> UUID | None:
        if name is None or not name.strip():
            return None
        return (await ensure_room_in(self._uow, name, self._now)).id

    # - - - Details of a matched lesson - - -

    def _managed(self, lesson: Lesson) -> bool:
        """True if EMIS may change the schedule: not hand-edited, not a manual entry."""
        by_hand = lesson.is_overridden and lesson.emis_class_id is None
        own = (
            lesson.timetable_entry_id is None
            or lesson.timetable_entry_id in self._emis_entries
        )
        return own and not by_hand

    async def _enrich(self, lesson: Lesson, item: EmisClass, keys: set[str]) -> None:
        before = (
            lesson.kind,
            lesson.emis_class_id,
            lesson.status,
            lesson.is_overridden,
            lesson.topic,
            lesson.emis_topic,
            lesson.starts_at,
        )
        lesson.kind = item.kind
        if self._managed(lesson):
            self._adopt(lesson, item, keys)
            if lesson.status == "cancelled" and lesson.emis_class_id == item.class_id:
                self._revive(lesson)
            self._follow_bell(lesson, item)
        if self._import_topics:
            self._follow_topic(lesson, item)
        after = (
            lesson.kind,
            lesson.emis_class_id,
            lesson.status,
            lesson.is_overridden,
            lesson.topic,
            lesson.emis_topic,
            lesson.starts_at,
        )
        if after != before:
            if await self._uow.lessons.try_save(lesson):
                self._tally.enriched += 1
                if before[2] != after[2]:
                    self._note(lesson)
            else:
                log.warning("emis_lesson_not_saved", lesson_id=str(lesson.id))
        if self._import_topics:
            self._collect_urls(lesson, item)

    @staticmethod
    def _follow_topic(lesson: Lesson, item: EmisClass) -> None:
        """Show the EMIS topic until a teacher writes their own."""
        topic = item.topic.name if item.topic else None
        if lesson.topic is None or lesson.topic == lesson.emis_topic:
            lesson.topic = topic
        lesson.emis_topic = topic

    def _follow_bell(self, lesson: Lesson, item: EmisClass) -> None:
        """A lesson EMIS moved is overridden: the generator leaves its time alone."""
        if not lesson.is_overridden or lesson.emis_class_id != item.class_id:
            return
        if lesson.status != "scheduled" or not lesson.starts_after(self._now):
            return
        weekday = class_weekday(item.date, self._term)
        bell = bell_for(self._term, lesson.period, weekday) if weekday else None
        if bell is None:
            return
        starts_at, ends_at = lesson_times(lesson.date, bell[0], bell[1])
        if (lesson.starts_at, lesson.ends_at) != (starts_at, ends_at):
            lesson.changes = merge_changes(
                lesson.changes,
                {
                    "time": [
                        time_label(lesson.starts_at, lesson.ends_at),
                        time_label(starts_at, ends_at),
                    ]
                },
            )
            lesson.starts_at, lesson.ends_at = starts_at, ends_at

    def _adopt(self, lesson: Lesson, item: EmisClass, keys: set[str]) -> None:
        """Remember which EMIS class the lesson is, unless it is another group's."""
        current = lesson.emis_class_id
        stale = current not in self._seen and set(lesson.audience) <= keys
        if current is None or stale:
            lesson.emis_class_id = item.class_id

    def _revive(self, lesson: Lesson) -> None:
        """EMIS lists the class again: undo the cancellation EMIS caused."""
        lesson.status = "scheduled"
        changes = dict(lesson.changes or {})
        changes.pop("status", None)
        lesson.changes = changes or None
        lesson.is_overridden = bool(changes)
        self._tally.revived += 1

    def _collect_urls(self, lesson: Lesson, item: EmisClass) -> None:
        topic = item.topic
        if topic is None:
            return
        found: tuple[tuple[str | None, MaterialKind], ...] = (
            (topic.topic_file_url, "classwork"),
            (topic.homework_file_url, "homework"),
            (topic.video_url, "video"),
        )
        for url, kind in found:
            if url:
                self._tally.urls.setdefault(
                    (lesson.id, url), EmisMaterial(lesson.id, url, topic.name, kind)
                )

    # - - - Classes EMIS dropped - - -

    async def _cancel_missing(self, lessons: Sequence[Lesson], keys: set[str]) -> None:
        for lesson in lessons:
            if (
                lesson.id in self._matched
                or lesson.emis_class_id is None
                or lesson.status != "scheduled"
                or not self._managed(lesson)
                or not lesson.starts_after(self._now)
                or not set(lesson.audience) <= keys
            ):
                continue
            superseded = lesson.id in self._superseded
            if lesson.emis_class_id in self._seen and not superseded:
                # EMIS lists the class, it only could not move: never a cancellation.
                log.warning("emis_listed_lesson_kept", lesson_id=str(lesson.id))
                continue
            lesson.status = "cancelled"
            lesson.is_overridden = True
            lesson.changes = merge_changes(
                lesson.changes, {"status": ["scheduled", "cancelled"]}
            )
            if superseded:
                lesson.emis_class_id = None  # the class lives on in the other lesson
            if await self._uow.lessons.try_save(lesson):
                self._tally.cancelled += 1
                self._note(lesson)

    def _note(self, lesson: Lesson) -> None:
        self._tally.changed.append(lesson.id)
        self._tally.room_ids.add(lesson.room_id)


def _by_slot(lessons: Sequence[Lesson], keys: set[str]) -> dict[SlotKey, Lesson]:
    """Index lessons by date, period and audience key; a scheduled lesson wins."""
    indexed: dict[SlotKey, Lesson] = {}
    for lesson in lessons:
        for key in lesson.audience:
            if key not in keys:
                continue
            slot = (lesson.date, lesson.period, key)
            current = indexed.get(slot)
            if current is None or (
                current.status == "cancelled" and lesson.status == "scheduled"
            ):
                indexed[slot] = lesson
    return indexed
