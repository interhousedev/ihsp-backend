"""The curriculum of a group as the API shows it."""

import datetime as dt
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.domain.curriculum.names import display_name
from app.modules.academic.domain.curriculum.records import (
    Curriculum,
    ExtraItem,
    SemesterSubject,
)
from app.modules.academic.domain.curriculum.semesters import current_semester
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.subject import LANGUAGES, Subject


@dataclass(frozen=True, slots=True)
class DirectionView:
    """The education direction."""

    emis_id: int | None
    name: str | None
    code: str | None


@dataclass(frozen=True, slots=True)
class RatingScaleView:
    """The rating scale of the curriculum."""

    min: int | None
    max: int | None


@dataclass(frozen=True, slots=True)
class CurriculumSubjectView:
    """A subject of a semester; ``subject_id`` is None until the subject exists."""

    subject_id: UUID | None
    emis_subject_id: int
    name: dict[str, str]
    subject_type_id: int | None
    study_hours: int | None
    class_hours: int | None
    independent_hours: int | None
    is_separated: bool


@dataclass(frozen=True, slots=True)
class CurriculumSemesterView:
    """A semester with its dates (None when only the subjects mention it)."""

    number: int
    starts_on: dt.date | None
    ends_on: dt.date | None
    is_current: bool
    subjects: list[CurriculumSubjectView] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CurriculumExtraView:
    """An exam or a vocational subject."""

    name: dict[str, str]
    study_hours: int | None


@dataclass(frozen=True, slots=True)
class CurriculumView:
    """The EMIS curriculum of a group."""

    emis_curriculum_id: int
    name: str
    speciality: dict[str, str] | None
    direction: DirectionView | None
    edu_form: str | None
    language_code: str | None
    rating_scale: RatingScaleView | None
    current_semester: int | None
    fetched_at: dt.datetime
    semesters: list[CurriculumSemesterView]
    exams: list[CurriculumExtraView]
    vocational_subjects: list[CurriculumExtraView]


async def build_curriculum_view(
    uow: ScheduleUnitOfWork, group: Group, today: dt.date
) -> CurriculumView | None:
    """Return the group's stored curriculum for the API, or None when it has none."""
    header = await uow.curricula.get(group.id)
    if header is None:
        return None
    rows = await uow.curricula.list_subjects(group.id)
    subjects = await uow.subjects.get_by_emis_ids({row.emis_subject_id for row in rows})
    now_in = current_semester(header.semester_dates, today)
    if now_in is None:
        now_in = group.current_semester
    return CurriculumView(
        emis_curriculum_id=header.emis_curriculum_id,
        name=header.name,
        speciality=dict(header.speciality) if header.speciality else None,
        direction=(
            DirectionView(
                header.direction.emis_id, header.direction.name, header.direction.code
            )
            if header.direction
            else None
        ),
        edu_form=header.edu_form,
        language_code=header.language_code,
        rating_scale=(
            RatingScaleView(header.rating_min, header.rating_max)
            if header.rating_min is not None or header.rating_max is not None
            else None
        ),
        current_semester=now_in,
        fetched_at=header.fetched_at,
        semesters=_semesters(header, rows, subjects, now_in),
        exams=[_extra(item) for item in header.exams],
        vocational_subjects=[_extra(item) for item in header.vocational],
    )


def _semesters(
    header: Curriculum,
    rows: list[SemesterSubject],
    subjects: dict[int, Subject],
    now_in: int | None,
) -> list[CurriculumSemesterView]:
    dates = {span.number: span for span in header.semester_dates}
    by_semester: dict[int, list[CurriculumSubjectView]] = {}
    for row in rows:
        by_semester.setdefault(row.semester_number, []).append(
            _subject(row, subjects.get(row.emis_subject_id))
        )
    numbers = sorted(set(dates) | set(by_semester))
    return [
        CurriculumSemesterView(
            number=number,
            starts_on=dates[number].starts_on if number in dates else None,
            ends_on=dates[number].ends_on if number in dates else None,
            is_current=number == now_in,
            subjects=sorted(
                by_semester.get(number, []),
                key=lambda item: (
                    display_name(item.name).casefold(),
                    item.emis_subject_id,
                ),
            ),
        )
        for number in numbers
    ]


def _subject(row: SemesterSubject, known: Subject | None) -> CurriculumSubjectView:
    """The academic subject's own name wins; EMIS's fills the languages it lacks."""
    names = {
        language: ((known.name.get(language) or "").strip() if known else "")
        or row.name.get(language, "").strip()
        for language in LANGUAGES
    }
    return CurriculumSubjectView(
        subject_id=known.id if known else None,
        emis_subject_id=row.emis_subject_id,
        name=names,
        subject_type_id=row.subject_type_id,
        study_hours=row.study_hours,
        class_hours=row.class_hours,
        independent_hours=row.independent_hours,
        is_separated=row.is_separated,
    )


def _extra(item: ExtraItem) -> CurriculumExtraView:
    return CurriculumExtraView(
        name={lang: item.name.get(lang, "") for lang in LANGUAGES},
        study_hours=item.study_hours,
    )
