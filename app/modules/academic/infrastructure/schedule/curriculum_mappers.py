"""Mapping curriculum rows (jsonb columns) to domain records and back."""

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.domain.curriculum.records import (
    Curriculum,
    DirectionInfo,
    ExtraItem,
    SemesterSpan,
    SemesterSubject,
    SubjectTotal,
)
from app.modules.academic.infrastructure.orm import GroupCurriculum as CurriculumRow
from app.modules.academic.infrastructure.orm import (
    GroupCurriculumSubject as CurriculumSubjectRow,
)


def _names(raw: Any) -> dict[str, str]:
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return {lang: str(data.get(lang) or "") for lang in ("uz", "ru", "en")}


def _spans_to_json(spans: Sequence[SemesterSpan]) -> list[dict[str, Any]]:
    return [
        {
            "number": span.number,
            "starts_on": span.starts_on.isoformat(),
            "ends_on": span.ends_on.isoformat(),
        }
        for span in spans
    ]


def _spans_from_json(raw: Any) -> list[SemesterSpan]:
    return [
        SemesterSpan(
            number=int(item["number"]),
            starts_on=dt.date.fromisoformat(item["starts_on"]),
            ends_on=dt.date.fromisoformat(item["ends_on"]),
        )
        for item in raw or []
    ]


def _totals_to_json(totals: Sequence[SubjectTotal]) -> list[dict[str, Any]]:
    return [
        {
            "emis_subject_id": total.emis_subject_id,
            "name": dict(total.name),
            "subject_type_id": total.subject_type_id,
            "study_hours": total.study_hours,
        }
        for total in totals
    ]


def _totals_from_json(raw: Any) -> list[SubjectTotal]:
    return [
        SubjectTotal(
            emis_subject_id=int(item["emis_subject_id"]),
            name=_names(item.get("name")),
            subject_type_id=item.get("subject_type_id"),
            study_hours=item.get("study_hours"),
        )
        for item in raw or []
    ]


def _extras_to_json(items: Sequence[ExtraItem]) -> list[dict[str, Any]]:
    return [
        {
            "emis_id": item.emis_id,
            "name": dict(item.name),
            "study_hours": item.study_hours,
        }
        for item in items
    ]


def _extras_from_json(raw: Any) -> list[ExtraItem]:
    return [
        ExtraItem(
            emis_id=item.get("emis_id"),
            name=_names(item.get("name")),
            study_hours=item.get("study_hours"),
        )
        for item in raw or []
    ]


def curriculum_values(curriculum: Curriculum) -> dict[str, Any]:
    """The column values of a curriculum header (without created_at, updated_at)."""
    direction = curriculum.direction
    return {
        "emis_curriculum_id": curriculum.emis_curriculum_id,
        "name": curriculum.name,
        "speciality": dict(curriculum.speciality) if curriculum.speciality else None,
        "direction": (
            {
                "emis_id": direction.emis_id,
                "name": direction.name,
                "code": direction.code,
            }
            if direction
            else None
        ),
        "edu_form": curriculum.edu_form,
        "language_code": curriculum.language_code,
        "rating_min": curriculum.rating_min,
        "rating_max": curriculum.rating_max,
        "semesters_count": curriculum.semesters_count,
        "semester_dates": _spans_to_json(curriculum.semester_dates),
        "subject_totals": _totals_to_json(curriculum.subject_totals),
        "exams": _extras_to_json(curriculum.exams),
        "vocational": _extras_to_json(curriculum.vocational),
        "fetched_at": curriculum.fetched_at,
    }


def curriculum_to_entity(row: CurriculumRow) -> Curriculum:
    """Map a curriculum row, parsing its jsonb columns."""
    direction = row.direction
    return Curriculum(
        group_id=row.group_id,
        emis_curriculum_id=row.emis_curriculum_id,
        name=row.name,
        fetched_at=row.fetched_at,
        speciality=_names(row.speciality) if row.speciality else None,
        direction=(
            DirectionInfo(
                direction.get("emis_id"), direction.get("name"), direction.get("code")
            )
            if direction
            else None
        ),
        edu_form=row.edu_form,
        language_code=row.language_code,
        rating_min=row.rating_min,
        rating_max=row.rating_max,
        semesters_count=row.semesters_count,
        semester_dates=_spans_from_json(row.semester_dates),
        subject_totals=_totals_from_json(row.subject_totals),
        exams=_extras_from_json(row.exams),
        vocational=_extras_from_json(row.vocational),
    )


def subject_row_values(group_id: UUID, subject: SemesterSubject) -> dict[str, Any]:
    """The column values of one semester subject row."""
    return {
        "group_id": group_id,
        "semester_number": subject.semester_number,
        "emis_subject_id": subject.emis_subject_id,
        "name": dict(subject.name),
        "subject_type_id": subject.subject_type_id,
        "study_hours": subject.study_hours,
        "class_hours": subject.class_hours,
        "independent_hours": subject.independent_hours,
        "is_separated": subject.is_separated,
    }


def subject_to_entity(row: CurriculumSubjectRow) -> SemesterSubject:
    """Map a semester subject row."""
    return SemesterSubject(
        semester_number=row.semester_number,
        emis_subject_id=row.emis_subject_id,
        name=_names(row.name),
        subject_type_id=row.subject_type_id,
        study_hours=row.study_hours,
        class_hours=row.class_hours,
        independent_hours=row.independent_hours,
        is_separated=row.is_separated,
    )
