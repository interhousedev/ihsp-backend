"""Turn parsed EMIS responses into the contract dataclasses."""

import hashlib
import json
import unicodedata
from datetime import date, datetime, time
from typing import Any

from app.modules.identity.application.register_models import EmisRequestError
from app.modules.identity.infrastructure.emis.models.responses.class_hours import (
    ClassHoursV1DTO,
)
from app.modules.identity.infrastructure.emis.models.responses.class_schedules import (
    ClassSchedulesV1DTO,
    ClassTeacherV1DTO,
    ClassV1DTO,
    SubjectV1DTO,
    TopicV1DTO,
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
    EmisClass,
    EmisClassHour,
    EmisMark,
    EmisMarkType,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
    EmisTeacher,
    EmisTopic,
)
from app.shared.lesson_kind import LessonKind
from app.shared.text import normalize_group_name, title_case

import structlog

log = structlog.get_logger(__name__)

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


# - - - Class schedules - - -

# EMIS names the class types in Uzbek; apostrophes come in several shapes, so the
# names are compared as bare letters ("Ma'ruza" -> "maruza").
_CLASS_KINDS: dict[str, LessonKind] = {
    "maruza": "lecture",
    "lecture": "lecture",
    "лекция": "lecture",
    "amaliyot": "practice",
    "practice": "practice",
    "практика": "practice",
    "oraliqnazorat": "midterm",
    "midtermcontrol": "midterm",
    "рубежныйконтроль": "midterm",
    "yakuniynazorat": "final",
    "finalcontrol": "final",
    "итоговыйконтроль": "final",
}
_HTTP = ("http://", "https://")


def class_kind(name: str | None) -> LessonKind:
    """Map an EMIS class type name to a lesson kind; unknown names are "other"."""
    letters = "".join(
        ch
        for ch in (name or "").casefold()
        if ch.isalpha() and unicodedata.category(ch) != "Lm"  # not ʼ or ʻ
    )
    return _CLASS_KINDS.get(letters, "other")


def _parse_day(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError as exc:
        raise EmisRequestError(f"unexpected class date {value!r}") from exc


def _subject(dto: SubjectV1DTO) -> EmisSubject:
    uz, ru, en = (
        (dto.name.uz or "").strip(),
        (dto.name.ru or "").strip(),
        (dto.name.en or "").strip(),
    )
    fallback = uz or ru or en or f"Subject {dto.id}"
    return EmisSubject(dto.id, uz or fallback, ru or fallback, en or fallback)


def _teacher(row: ClassTeacherV1DTO) -> EmisTeacher | None:
    if row.teacher is None:
        return None
    person = row.teacher.citizen
    first, last = title_case(person.first_name), title_case(person.last_name)
    if not first and not last:
        return None
    middle = title_case(person.middle_name or "")
    return EmisTeacher(row.teacher.id, first, last, middle or None)


def _url(value: str | None) -> str | None:
    url = (value or "").strip()
    return url if url.lower().startswith(_HTTP) else None


def _topic(dto: TopicV1DTO | None) -> EmisTopic | None:
    name = ((dto.name if dto else None) or "").strip()
    if dto is None or not name:
        return None
    return EmisTopic(
        name=name,
        description=(dto.description or "").strip() or None,
        topic_file_url=_url(dto.topic_file_url),
        homework_file_url=_url(dto.homework_file_url),
        video_url=_url(dto.video_url),
    )


def _class(day: date, item: ClassV1DTO) -> EmisClass | None:
    """Map a class by its first teacher row that names a subject."""
    if item.pair_number < 0:
        raise EmisRequestError(f"unexpected pair number {item.pair_number}")
    for row in item.teachers or []:
        if row.edu_subject is None:
            continue
        half = row.group_number if item.is_seperated else None
        room = ((row.room.name if row.room else None) or "").strip()
        return EmisClass(
            class_id=item.id,
            date=day,
            pair_number=item.pair_number,
            subject=_subject(row.edu_subject),
            teacher=_teacher(row),
            room=room or None,
            subgroup=1 if half == 1 else 2 if half == 2 else None,
            kind=class_kind(row.class_type.name if row.class_type else None),
            topic=_topic(row.topic),
        )
    return None


def to_classes(dto: ClassSchedulesV1DTO) -> list[EmisClass]:
    """Map the days to classes, ordered by date and pair; skip one with no subject."""
    classes: list[EmisClass] = []
    for day in dto.results:
        when = _parse_day(day.date)
        for item in day.classes or []:
            mapped = _class(when, item)
            if mapped is None:
                log.warning("emis_class_without_subject", class_id=item.id)
            else:
                classes.append(mapped)
    classes.sort(key=lambda c: (c.date, c.pair_number, c.class_id))
    return classes
