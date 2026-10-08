"""Turn parsed EMIS responses into the contract dataclasses."""

import hashlib
import json
from datetime import date, datetime, time
from typing import Any

from app.modules.identity.application.register_models import EmisRequestError
from app.modules.identity.infrastructure.emis.models.responses.class_hours import (
    ClassHoursV1DTO,
)
from app.modules.identity.infrastructure.emis.models.responses.curriculum import (
    CurriculumV1DTO,
)
from app.modules.identity.infrastructure.emis.models.responses.profile import (
    ProfileV1DTO,
)
from app.modules.identity.infrastructure.emis.models.responses.ratings import (
    RatingsV1DTO,
)
from app.shared.contracts.emis import (
    EmisClassHour,
    EmisMark,
    EmisMarkType,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
)
from app.shared.text import normalize_group_name, title_case

# EMIS names the rating groups in Uzbek; the prefix is enough to tell them apart.
_RATING_PREFIXES: tuple[tuple[str, EmisMarkType], ...] = (
    ("joriy", EmisMarkType.LESSON),
    ("oraliq", EmisMarkType.MIDTERM),
    ("yakuniy", EmisMarkType.FINAL),
)


def to_profile(dto: ProfileV1DTO) -> EmisProfile:
    """Map the profile; names to title case, the group name to Latin upper case."""
    middle = title_case(dto.citizen.middle_name or "")
    return EmisProfile(
        emis_student_id=dto.id,
        first_name=title_case(dto.citizen.first_name),
        last_name=title_case(dto.citizen.last_name),
        middle_name=middle or None,
        institution_id=dto.institution_id,
        group_emis_id=dto.edu_group_id,
        group_name=normalize_group_name(dto.edu_group.name),
        current_semester=dto.edu_group.current_semester,
        curriculum_id=dto.edu_group.curriculum_id,
    )


def to_subjects(dto: CurriculumV1DTO) -> list[EmisSubject]:
    """Map the curriculum; an empty name falls back to another language."""
    subjects: list[EmisSubject] = []
    for item in dto.edu_subject:
        name = item.edu_subject.name
        uz, ru, en = (
            (name.uz or "").strip(),
            (name.ru or "").strip(),
            (name.en or "").strip(),
        )
        fallback = uz or ru or en or f"Subject {item.edu_subject_id}"
        subjects.append(
            EmisSubject(
                emis_subject_id=item.edu_subject_id,
                name_uz=uz or fallback,
                name_ru=ru or fallback,
                name_en=en or fallback,
            )
        )
    return subjects


def _mark_type(name: str) -> EmisMarkType | None:
    lowered = name.strip().lower()
    for prefix, mark_type in _RATING_PREFIXES:
        if lowered.startswith(prefix):
            return mark_type
    return None


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError as exc:
        raise EmisRequestError(f"unexpected mark date {value!r}") from exc


def _semester_rating(value: float | str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        rating = round(float(value))
    except ValueError as exc:
        raise EmisRequestError(f"unexpected semester rating {value!r}") from exc
    return rating or None  # EMIS sends 0 while the rating is not set


def payload_hash(result: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the response's ``result`` object."""
    canonical = json.dumps(result, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def to_ratings(
    dto: RatingsV1DTO, *, raw_result: dict[str, Any], subject_id: int, semester: int
) -> EmisSubjectRatings:
    """Map the ratings of one subject; unknown rating groups are skipped."""
    marks: list[EmisMark] = []
    for group in dto.ratings or []:
        mark_type = _mark_type(group.name)
        if mark_type is None:
            continue
        marks.extend(
            EmisMark(
                type=mark_type, date=_parse_date(daily.class_date), value=daily.rating
            )
            for daily in group.daily_ratings or []
        )
    return EmisSubjectRatings(
        emis_subject_id=subject_id,
        semester=semester,
        semester_rating=_semester_rating(dto.semester_rating),
        marks=tuple(marks),
        payload_hash=payload_hash(raw_result),
    )


def _parse_clock(value: str) -> time:
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError as exc:
        raise EmisRequestError(f"unexpected class hour time {value!r}") from exc


def to_class_hours(dto: ClassHoursV1DTO) -> list[EmisClassHour]:
    """Map the bells ordered by pair; a pair that ends before it begins is rejected."""
    hours: list[EmisClassHour] = []
    for item in sorted(dto.results, key=lambda pair: pair.pair_number):
        begin, end = _parse_clock(item.begin_time), _parse_clock(item.end_time)
        if item.pair_number < 0 or not begin < end:
            raise EmisRequestError(f"unexpected class hour {item.pair_number}")
        hours.append(EmisClassHour(item.pair_number, begin, end))
    return hours
