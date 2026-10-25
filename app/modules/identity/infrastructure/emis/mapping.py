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
    CurriculumItemV1DTO,
    CurriculumV1DTO,
    DirectionV1DTO,
    EduSubjectV1DTO,
    NamedItemV1DTO,
    SemesterDatesV1DTO,
    SemesterSubjectV1DTO,
    SubjectNameV1DTO,
    YearV1DTO,
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
    EmisCurriculum,
    EmisCurriculumItem,
    EmisCurriculumSubject,
    EmisDirection,
    EmisMark,
    EmisMarkType,
    EmisName,
    EmisProfile,
    EmisSemesterDates,
    EmisSemesterSubject,
    EmisSubject,
    EmisSubjectRatings,
    EmisTeacher,
    EmisTopic,
    EmisYear,
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


# - - - Curriculum - - -

_EMIS_DATE = "%d.%m.%Y"


def to_subjects(dto: CurriculumV1DTO) -> list[EmisSubject]:
    """Map the curriculum to its subjects; an empty name falls back to another."""
    return curriculum_subjects(to_curriculum(dto))


def curriculum_subjects(curriculum: EmisCurriculum) -> list[EmisSubject]:
    """The subjects of a curriculum: uz, else ru, else en, else "Subject <id>"."""
    subjects: list[EmisSubject] = []
    for item in curriculum.subjects:
        name = item.name
        fallback = name.uz or name.ru or name.en or f"Subject {item.emis_subject_id}"
        subjects.append(
            EmisSubject(
                emis_subject_id=item.emis_subject_id,
                name_uz=name.uz or fallback,
                name_ru=name.ru or fallback,
                name_en=name.en or fallback,
            )
        )
    return subjects


def to_curriculum(dto: CurriculumV1DTO) -> EmisCurriculum:
    """Map the whole curriculum; every part but the ids may be missing.

    Empty strings are None (``""`` inside ``EmisName``); a semester whose dates
    cannot be read is left out with a warning.
    """
    template = dto.curriculum_template
    return EmisCurriculum(
        emis_id=dto.id,
        name=_text(dto.name) or "",
        direction=_direction(dto.edu_direction),
        speciality=_speciality(dto.speciality),
        edu_form=_text(dto.edu_form.name) if dto.edu_form else None,
        language_code=_text(dto.edu_language.code) if dto.edu_language else None,
        rating_min=dto.rating_type.min_rating if dto.rating_type else None,
        rating_max=dto.rating_type.max_rating if dto.rating_type else None,
        start_year=_year(dto.start_year),
        end_year=_year(dto.end_year),
        semesters_count=template.number_of_semesters if template else None,
        status=_text(dto.status),
        semesters=_semesters(dto.semester_dates),
        subjects=tuple(_curriculum_subject(item) for item in dto.edu_subject),
        semester_subjects=_semester_subjects(dto.semester_edu_subjects),
        exams=tuple(_curriculum_item(item) for item in dto.exams),
        vocational_subjects=tuple(
            _curriculum_item(item) for item in dto.vocational_subjects
        ),
    )


def _text(value: str | None) -> str | None:
    """Stripped text, None when empty."""
    return (value or "").strip() or None


def _emis_name(name: SubjectNameV1DTO | None) -> EmisName:
    """The three languages as EMIS sent them, stripped; no fallback here."""
    if name is None:
        return EmisName()
    return EmisName(
        (name.uz or "").strip(), (name.ru or "").strip(), (name.en or "").strip()
    )


def _speciality(name: SubjectNameV1DTO | None) -> EmisName | None:
    mapped = _emis_name(name)
    return mapped if mapped != EmisName() else None


def _direction(dto: DirectionV1DTO | None) -> EmisDirection | None:
    if dto is None:
        return None
    direction = EmisDirection(dto.id, _text(dto.name), _text(dto.code))
    return direction if direction != EmisDirection(None, None, None) else None


def _optional_date(value: str | None) -> date | None:
    """A date as ``DD.MM.YYYY`` or ISO; anything else is None."""
    text = (value or "").strip()
    for parse in (_emis_datetime, datetime.fromisoformat):
        try:
            return parse(text).date()
        except ValueError:
            continue
    return None


def _emis_datetime(text: str) -> datetime:
    return datetime.strptime(text, _EMIS_DATE)


def _year(dto: YearV1DTO | None) -> EmisYear | None:
    if dto is None:
        return None
    year = EmisYear(
        code=_text(dto.code),
        name=_text(dto.name),
        from_date=_optional_date(dto.from_date),
        to_date=_optional_date(dto.to_date),
    )
    return year if year != EmisYear(None, None, None, None) else None


def _semesters(items: list[SemesterDatesV1DTO | None]) -> tuple[EmisSemesterDates, ...]:
    """Number the semesters by their place in the list; skip one with bad dates."""
    semesters: list[EmisSemesterDates] = []
    for number, item in enumerate(items, start=1):
        starts = _optional_date(item.start_date) if item else None
        ends = _optional_date(item.end_date) if item else None
        if starts is None or ends is None or ends < starts:
            log.warning(
                "emis_semester_dates_skipped",
                semester=number,
                start_date=item.start_date if item else None,
                end_date=item.end_date if item else None,
            )
            continue
        semesters.append(EmisSemesterDates(number, starts, ends))
    return tuple(semesters)


def _type_id(subject: EduSubjectV1DTO | None) -> int | None:
    if subject is None:
        return None
    if subject.edu_subject_type is not None and subject.edu_subject_type.id:
        return subject.edu_subject_type.id
    return subject.edu_subject_type_id


def _curriculum_subject(item: CurriculumItemV1DTO) -> EmisCurriculumSubject:
    name = item.edu_subject.name if item.edu_subject else None
    return EmisCurriculumSubject(
        emis_subject_id=item.edu_subject_id,
        name=_emis_name(name),
        subject_type_id=_type_id(item.edu_subject),
        study_hours=item.study_hours,
    )


def _semester_subjects(
    semesters: list[list[SemesterSubjectV1DTO]],
) -> tuple[EmisSemesterSubject, ...]:
    """The subjects semester by semester; a missing number is the list position."""
    return tuple(
        _semester_subject(item, position)
        for position, items in enumerate(semesters, start=1)
        for item in items
    )


def _semester_subject(item: SemesterSubjectV1DTO, position: int) -> EmisSemesterSubject:
    name = item.edu_subject.name if item.edu_subject else None
    return EmisSemesterSubject(
        semester_number=item.semester_number or position,
        emis_subject_id=item.edu_subject_id,
        name=_emis_name(name),
        subject_type_id=_type_id(item.edu_subject),
        study_hours=item.study_hours,
        class_hours=item.class_hours,
        independent_hours=item.independent_work_hours,
        is_separated=item.is_seperated,
    )


def _curriculum_item(item: NamedItemV1DTO) -> EmisCurriculumItem:
    return EmisCurriculumItem(item.id, _emis_name(item.name), item.study_hours)


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
    absent: set[date] = set()
    flagged = False
    for group in dto.ratings or []:
        mark_type = _mark_type(group.name)
        for daily in group.daily_ratings or []:
            if daily.absent is not None:
                flagged = True
                if daily.absent:
                    absent.add(_parse_date(daily.class_date))
            if mark_type is not None and daily.rating is not None:
                marks.append(
                    EmisMark(
                        type=mark_type,
                        date=_parse_date(daily.class_date),
                        value=daily.rating,
                    )
                )
    return EmisSubjectRatings(
        emis_subject_id=subject_id,
        semester=semester,
        semester_rating=_semester_rating(dto.semester_rating),
        marks=tuple(marks),
        payload_hash=payload_hash(raw_result),
        absent_dates=tuple(sorted(absent)) if flagged else None,
        absence_total=dto.absences,
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
