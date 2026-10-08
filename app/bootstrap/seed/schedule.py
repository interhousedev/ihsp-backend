"""Demo academic structure: term, bells, subjects, groups, timetable, lessons."""

import datetime as dt
from dataclasses import dataclass, replace
from uuid import UUID

from app.bootstrap.container import Container
from app.modules.academic.application.schedule.entry_builder import EntryInput
from app.modules.academic.application.schedule.results import TermData
from app.modules.academic.domain.schedule.term import Bell
from app.modules.identity.infrastructure.emis.fake import FAKE_SUBJECTS
from app.shared.actor import SYSTEM_ACTOR
from app.shared.base_error import ConflictError

import structlog

log = structlog.get_logger(__name__)

ACADEMIC_YEAR = "2026-2027"
TERM_START = dt.date(2026, 9, 2)
TERM_END = dt.date(2026, 12, 30)
NON_STUDY_DAYS = (dt.date(2026, 10, 1),)
BELLS = (
    (1, dt.time(8, 30), dt.time(9, 15)),
    (2, dt.time(9, 25), dt.time(10, 10)),
    (3, dt.time(10, 20), dt.time(11, 5)),
    (4, dt.time(11, 25), dt.time(12, 10)),
    (5, dt.time(12, 20), dt.time(13, 5)),
    (6, dt.time(13, 15), dt.time(14, 0)),
)
STUDY_WEEKDAYS = [1, 2, 3, 4, 5, 6]
LESSONS_PER_DAY = 5
DIVIDED_SUBJECTS = (103, 107)  # English and Informatics split into subgroups


@dataclass(frozen=True, slots=True)
class GroupSpec:
    """A demo group as EMIS names it."""

    key: str
    name: str
    emis_group_id: int
    semester: int
    rooms: tuple[str, ...]


GROUPS = (
    GroupSpec("2TN2", "2TN2", 3292, 3, ("101", "204")),
    GroupSpec("1TN1", "1TN1", 3291, 1, ("102", "Klaster")),
)

# subject EMIS id -> teacher key; divided subjects list one teacher per subgroup.
TEACHER_OF: dict[int, tuple[str, ...]] = {
    101: ("math",),
    102: ("math",),
    103: ("languages", "uzbek"),
    104: ("languages",),
    105: ("uzbek",),
    106: ("humanities",),
    107: ("it", "humanities"),
    108: ("it",),
}


@dataclass(slots=True)
class Structure:
    """Ids the later seed steps need."""

    term: TermData
    group_ids: dict[str, UUID]
    subject_ids: dict[int, UUID]


async def _ensure_term(container: Container) -> TermData:
    schedule = container.academic.schedule
    for term in await schedule.list_terms.execute():
        if term.academic_year == ACADEMIC_YEAR and term.half == 1:
            return term
    bells = [
        Bell(period=period, start=start, end=end, weekdays=STUDY_WEEKDAYS)
        for period, start, end in BELLS
    ]
    return await schedule.create_term.execute(
        academic_year=ACADEMIC_YEAR,
        half=1,
        starts_on=TERM_START,
        ends_on=TERM_END,
        bells=bells,
        non_study_days=NON_STUDY_DAYS,
        moved_days=[],
    )


async def _ensure_groups(container: Container) -> dict[str, UUID]:
    schedule = container.academic.schedule
    groups = await schedule.list_groups.execute(None)
    existing = {group.name.casefold(): group.id for group in groups}
    ids: dict[str, UUID] = {}
    for spec in GROUPS:
        found = existing.get(spec.name.casefold())
        if found is None:
            created = await schedule.create_group.execute(
                name=spec.name,
                emis_group_id=spec.emis_group_id,
                current_semester=spec.semester,
            )
            found = created.id
        ids[spec.key] = found
    return ids


async def _ensure_subjects(
    container: Container, group_ids: dict[str, UUID]
) -> dict[int, UUID]:
    schedule = container.academic.schedule
    for group_id in group_ids.values():
        await schedule.enrollment.sync_subjects(
            group_id=group_id, subjects=FAKE_SUBJECTS
        )
    subjects = {s.emis_subject_id: s.id for s in await schedule.list_subjects.execute()}
    for emis_id in DIVIDED_SUBJECTS:
        await schedule.update_subject.execute(subjects[emis_id], can_be_divided=True)
    return {emis_id: subjects[emis_id] for emis_id in TEACHER_OF}


def _slots() -> list[tuple[int, int]]:
    return [
        (day, period) for day in range(1, 6) for period in range(1, LESSONS_PER_DAY + 1)
    ]


async def _try_entry(container: Container, data: EntryInput) -> UUID | None:
    try:
        entry = await container.academic.schedule.create_entry.execute(
            SYSTEM_ACTOR, data
        )
    except ConflictError:
        return None
    return entry.id


async def _fill_timetable(
    container: Container,
    term: TermData,
    group_ids: dict[str, UUID],
    subject_ids: dict[int, UUID],
    teachers: dict[str, UUID],
) -> int:
    """A full week for both groups, without conflicts.

    A slot whose teacher or room is taken tries the next subject.
    """
    subject_order = list(TEACHER_OF)
    created = 0
    for offset, spec in enumerate(GROUPS):
        for index, (day, period) in enumerate(_slots()):
            for attempt in range(len(subject_order)):
                emis_id = subject_order[
                    (index + offset * 3 + attempt) % len(subject_order)
                ]
                rooms = spec.rooms[(index + attempt) % 2 :] + spec.rooms
                if await _add_subject(
                    container,
                    EntryInput(
                        term_id=term.id,
                        weekday=day,
                        period=period,
                        week_parity="every",
                        subject_id=subject_ids[emis_id],
                        teacher_id=None,
                        room_name=None,
                        audience=[(group_ids[spec.key], None)],
                        valid_from=term.starts_on,
                        valid_to=None,
                    ),
                    [teachers[key] for key in TEACHER_OF[emis_id]],
                    rooms,
                    divided=emis_id in DIVIDED_SUBJECTS,
                ):
                    created += 1
                    break
    return created


async def _add_subject(
    container: Container,
    base: EntryInput,
    teacher_ids: list[UUID],
    rooms: tuple[str, ...],
    *,
    divided: bool,
) -> bool:
    """Create the entries of one subject in a slot; undo them all if one clashes."""
    group_id = base.audience[0][0]
    made: list[UUID] = []
    for position, teacher_id in enumerate(teacher_ids):
        entry_id = await _try_entry(
            container,
            replace(
                base,
                teacher_id=teacher_id,
                room_name=rooms[position % len(rooms)],
                audience=[(group_id, position + 1 if divided else None)],
            ),
        )
        if entry_id is None:
            for done in made:
                await container.academic.schedule.delete_entry.execute(done)
            return False
        made.append(entry_id)
    return True


async def seed_structure(container: Container, teachers: dict[str, UUID]) -> Structure:
    """Create the term, groups, subjects and timetable; safe to run again."""
    term = await _ensure_term(container)
    group_ids = await _ensure_groups(container)
    subject_ids = await _ensure_subjects(container, group_ids)
    existing = await container.academic.schedule.list_entries.execute(
        SYSTEM_ACTOR, term_id=term.id
    )
    if not existing:
        created = await _fill_timetable(
            container, term, group_ids, subject_ids, teachers
        )
        log.info("seed_timetable_created", entries=created)
    return Structure(term=term, group_ids=group_ids, subject_ids=subject_ids)


async def generate_lessons(container: Container, term: TermData) -> int:
    """Generate lessons from the first day of the term to two weeks from now."""
    today = container.clock.now().date()
    start = max(term.starts_on, min(today, term.ends_on))
    first = term.starts_on if today > term.starts_on else start
    days = (min(today + dt.timedelta(days=14), term.ends_on) - first).days + 1
    return int(
        await container.academic.schedule.generate_lessons.execute(
            term_id=term.id, from_date=first, days=max(days, 1)
        )
    )
