"""The curriculum of a group as stored from EMIS."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.academic.domain.curriculum.names import name_dict
from app.shared.contracts.emis import (
    EmisCurriculum,
    EmisCurriculumItem,
    EmisCurriculumSubject,
    EmisSemesterSubject,
)


@dataclass(frozen=True, slots=True)
class SemesterSpan:
    """The dates of one semester of the curriculum."""

    number: int
    starts_on: dt.date
    ends_on: dt.date


@dataclass(frozen=True, slots=True)
class DirectionInfo:
    """The education direction of the curriculum."""

    emis_id: int | None
    name: str | None
    code: str | None


@dataclass(frozen=True, slots=True)
class SubjectTotal:
    """A subject of the whole curriculum with its total hours."""

    emis_subject_id: int
    name: dict[str, str]
    subject_type_id: int | None
    study_hours: int | None


@dataclass(frozen=True, slots=True)
class ExtraItem:
    """An exam or a vocational subject of the curriculum."""

    emis_id: int | None
    name: dict[str, str]
    study_hours: int | None


@dataclass(frozen=True, slots=True)
class SemesterSubject:
    """A subject taught in one semester, with its hours; names as EMIS sent them."""

    semester_number: int
    emis_subject_id: int
    name: dict[str, str]
    subject_type_id: int | None
    study_hours: int | None
    class_hours: int | None
    independent_hours: int | None
    is_separated: bool


@dataclass(slots=True)
class Curriculum:
    """The stored curriculum of a group (the header; subjects are stored apart)."""

    group_id: UUID
    emis_curriculum_id: int
    name: str
    fetched_at: dt.datetime
    speciality: dict[str, str] | None = None
    direction: DirectionInfo | None = None
    edu_form: str | None = None
    language_code: str | None = None
    rating_min: int | None = None
    rating_max: int | None = None
    semesters_count: int | None = None
    semester_dates: list[SemesterSpan] = field(default_factory=list)
    subject_totals: list[SubjectTotal] = field(default_factory=list)
    exams: list[ExtraItem] = field(default_factory=list)
    vocational: list[ExtraItem] = field(default_factory=list)


def curriculum_from_emis(
    group_id: UUID, source: EmisCurriculum, fetched_at: dt.datetime
) -> Curriculum:
    """Map what EMIS sent to the stored header."""
    direction = source.direction
    return Curriculum(
        group_id=group_id,
        emis_curriculum_id=source.emis_id,
        name=source.name,
        fetched_at=fetched_at,
        speciality=name_dict(source.speciality) if source.speciality else None,
        direction=(
            DirectionInfo(direction.emis_id, direction.name, direction.code)
            if direction
            else None
        ),
        edu_form=source.edu_form,
        language_code=source.language_code,
        rating_min=source.rating_min,
        rating_max=source.rating_max,
        semesters_count=source.semesters_count,
        semester_dates=[
            SemesterSpan(item.number, item.starts_on, item.ends_on)
            for item in sorted(source.semesters, key=lambda item: item.number)
        ],
        subject_totals=[_total(item) for item in source.subjects],
        exams=[_extra(item) for item in source.exams],
        vocational=[_extra(item) for item in source.vocational_subjects],
    )


def semester_subjects_from_emis(
    rows: Sequence[EmisSemesterSubject],
) -> list[SemesterSubject]:
    """Map the per-semester subjects; a subject listed twice counts once."""
    seen: dict[tuple[int, int], SemesterSubject] = {}
    for row in rows:
        seen.setdefault(
            (row.semester_number, row.emis_subject_id),
            SemesterSubject(
                semester_number=row.semester_number,
                emis_subject_id=row.emis_subject_id,
                name=name_dict(row.name),
                subject_type_id=row.subject_type_id,
                study_hours=row.study_hours,
                class_hours=row.class_hours,
                independent_hours=row.independent_hours,
                is_separated=row.is_separated,
            ),
        )
    return sorted(seen.values(), key=lambda s: (s.semester_number, s.emis_subject_id))


def _total(item: EmisCurriculumSubject) -> SubjectTotal:
    return SubjectTotal(
        emis_subject_id=item.emis_subject_id,
        name=name_dict(item.name),
        subject_type_id=item.subject_type_id,
        study_hours=item.study_hours,
    )


def _extra(item: EmisCurriculumItem) -> ExtraItem:
    return ExtraItem(
        emis_id=item.emis_id, name=name_dict(item.name), study_hours=item.study_hours
    )
