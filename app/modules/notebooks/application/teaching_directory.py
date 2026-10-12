"""What a teacher teaches: the subjects, each with the groups (and subgroups)."""

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from app.modules.notebooks.application.material_audience import parse_key
from app.modules.notebooks.ports.term_calendar import TermCalendar
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries

NO_TERM_DAYS = 180  # without a term calendar: half a year around today


@dataclass(frozen=True, slots=True)
class TeachingGroup:
    """A group, or one subgroup of it, the teacher teaches a subject to."""

    group_id: UUID
    group_name: str
    subgroup: int | None


@dataclass(slots=True)
class TeachingSubject:
    """A subject the teacher teaches, with its EMIS id and groups."""

    subject_id: UUID
    name: str
    edu_subject_id: int | None
    groups: list[TeachingGroup] = field(default_factory=list)

    def teaches(self, group_id: UUID, subgroup: int | None) -> bool:
        """True when the teacher teaches this group (and subgroup) the subject."""
        return any(
            g.group_id == group_id
            and (subgroup is None or g.subgroup in (None, subgroup))
            for g in self.groups
        )


class TeachingDirectory:
    """Reads the subjects and groups a teacher has this term from the timetable."""

    def __init__(
        self, *, schedule: ScheduleQueries, terms: TermCalendar | None, clock: Clock
    ) -> None:
        """Store the collaborators (without `terms`: half a year around today)."""
        self.schedule = schedule
        self.terms = terms
        self.clock = clock

    async def subjects(self, teacher_id: UUID) -> list[TeachingSubject]:
        """The teacher's subjects by name; groups by name and subgroup."""
        today = local_today(self.clock)
        window = await self.terms.current_term_dates(today) if self.terms else None
        start, end = window or (
            today - timedelta(days=NO_TERM_DAYS),
            today + timedelta(days=NO_TERM_DAYS),
        )
        lessons = await self.schedule.lessons_for_teacher(teacher_id, start, end)
        found: dict[UUID, TeachingSubject] = {}
        seen: set[tuple[UUID, UUID, int | None]] = set()
        for lesson in lessons:
            subject = found.get(lesson.subject_id)
            if subject is None:
                subject = TeachingSubject(
                    subject_id=lesson.subject_id,
                    name=lesson.subject_name,
                    edu_subject_id=await self.schedule.subject_emis_id(
                        lesson.subject_id
                    ),
                )
                found[lesson.subject_id] = subject
            for key, label in zip(lesson.audience, lesson.group_names, strict=False):
                group_id, subgroup = parse_key(key)
                if (lesson.subject_id, group_id, subgroup) in seen:
                    continue
                seen.add((lesson.subject_id, group_id, subgroup))
                name = label if subgroup is None else label.rsplit("/", 1)[0]
                subject.groups.append(TeachingGroup(group_id, name, subgroup))
        for subject in found.values():
            subject.groups.sort(
                key=lambda g: (g.group_name.casefold(), g.subgroup or 0)
            )
        return sorted(found.values(), key=lambda s: s.name.casefold())

    async def subject(
        self, teacher_id: UUID, subject_id: UUID
    ) -> TeachingSubject | None:
        """One of the teacher's subjects, None when they do not teach it."""
        return next(
            (s for s in await self.subjects(teacher_id) if s.subject_id == subject_id),
            None,
        )
