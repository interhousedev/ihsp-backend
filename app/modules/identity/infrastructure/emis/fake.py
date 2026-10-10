"""Fake EMIS for ``EMIS__MODE=fake``: 30 students, 8 subjects, marks, timetable."""

import datetime as dt
import json
import re
from dataclasses import dataclass, replace
from datetime import date, time, timedelta
from functools import cache
from pathlib import Path
from typing import Any

from app.modules.identity.application.register_models import (
    EmisAuthError,
    EmisRequestError,
)
from app.modules.identity.infrastructure.emis.fake_schedule import (
    Cell,
    cells_of,
    digest,
    week_body,
)
from app.modules.identity.infrastructure.emis.mapping import (
    curriculum_subjects,
    payload_hash,
    to_classes,
    to_curriculum,
)
from app.modules.identity.infrastructure.emis.models.responses.class_schedules import (
    ClassSchedulesV1DTO,
)
from app.modules.identity.infrastructure.emis.models.responses.curriculum import (
    CurriculumV1DTO,
)
from app.shared.clock import Clock, local_today
from app.shared.contracts.emis import (
    EmisClass,
    EmisClassHour,
    EmisCurriculum,
    EmisMark,
    EmisMarkType,
    EmisProfile,
    EmisSemesterDates,
    EmisSubject,
    EmisSubjectRatings,
    EmisTeacher,
    EmisYear,
)
from app.shared.text import normalize_group_name, title_case

FAKE_PASSWORD = "password"
FAKE_CURRICULUM_PATH = Path(__file__).parent / "fake_data" / "curriculum.json"
_YEAR = timedelta(weeks=52)  # the next cohort's semesters, on the same weekdays
FAKE_INSTITUTION_ID = 10815
_TOKEN_PREFIX = "fake-token:"
_SEMESTER_START = date(2026, 9, 2)  # first day of the current semester
_SEMESTER_LENGTH = timedelta(days=116)
_SEMESTER_GAP = timedelta(days=183)
_MIDTERM_DATE = date(2026, 10, 20)

_SURNAMES = (
    "ABDULLAYEV KARIMOV RASULOVA YUSUPOV ISMAILOVA TURSUNOV NAZAROVA SAIDOV "
    "MIRZAYEVA KHOLMATOV ALIYEVA RAKHIMOV SHARIPOVA UMAROV BEKMURODOVA ERGASHEV "
    "TOSHPULATOVA NURMATOV SULTANOVA JURAYEV ORIPOVA HAMIDOV ZOKIROVA "
    "ABDURAKHMONOV NISHONOVA SOBIROV MAKHMUDOVA QODIROV XOLIQOVA DAVRONOV"
).split()
_NAMES = (
    "ALISHER DILNOZA JAMSHID MADINA SARDOR NILUFAR BEKZOD ZARINA OYBEK SHAHZODA "
    "TIMUR LOLA AZIZ MAFTUNA JASUR GULNORA DONIYOR SEVARA RUSTAM KAMOLA ILHOM "
    "FERUZA SHERZOD MALIKA OTABEK DILOROM BAKHTIYOR NASIBA JAVOHIR YULDUZ"
).split()
_PATRONYMICS = (
    "ALISHEROVICH DILSHODOVNA JAMSHIDOVICH BAKHTIYOROVNA SARVAROVICH RUSTAMOVNA "
    "BEKZODOVICH ANVAROVNA OYBEKOVICH TIMUROVNA AZIZOVICH LAZIZOVNA JASUROVICH "
    "ULUGBEKOVNA DONIYOROVICH SHAVKATOVNA RUSTAMOVICH NODIROVNA ILHOMOVICH "
    "KOMILOVNA SHERZODOVICH ABROROVNA OTABEKOVICH FARHODOVNA BAKHTIYOROVICH "
    "ZAFAROVNA JAVOHIROVICH ERKINOVNA"
).split()

FAKE_SUBJECTS: tuple[EmisSubject, ...] = (
    EmisSubject(101, "Matematika", "Математика", "Mathematics"),
    EmisSubject(102, "Fizika", "Физика", "Physics"),
    EmisSubject(103, "Ingliz tili", "Английский язык", "English"),
    EmisSubject(104, "Rus tili", "Русский язык", "Russian"),
    EmisSubject(105, "O'zbek tili", "Узбекский язык", "Uzbek"),
    EmisSubject(106, "Tarix", "История", "History"),
    EmisSubject(107, "Informatika", "Информатика", "Informatics"),
    EmisSubject(108, "Kimyo", "Химия", "Chemistry"),
)


# The real response of ``student-profiles/class-hours/``: five 80-minute pairs.
FAKE_CLASS_HOURS: tuple[EmisClassHour, ...] = (
    EmisClassHour(0, time(8, 30), time(9, 50)),
    EmisClassHour(1, time(10, 10), time(11, 30)),
    EmisClassHour(2, time(12, 10), time(13, 30)),
    EmisClassHour(3, time(13, 40), time(15, 0)),
    EmisClassHour(4, time(15, 10), time(16, 30)),
)

_MATH = EmisTeacher(9001, "Gulnora", "Kalandarova", "Akbarovna")
_LANGUAGES = EmisTeacher(9002, "Sardor", "Yuldashev", "Rustamovich")
_UZBEK = EmisTeacher(9003, "Madina", "Ismoilova", None)
_HUMANITIES = EmisTeacher(9004, "Timur", "Nazarov", "Aliyevich")
_IT = EmisTeacher(9005, "Oybek", "Rahimov", None)

# subject EMIS id -> (teacher of the whole group | teachers of halves 1 and 2).
_TEACHERS_OF: dict[int, tuple[EmisTeacher, ...]] = {
    101: (_MATH,),
    102: (_MATH,),
    103: (_LANGUAGES, _UZBEK),  # English is taught by halves
    104: (_LANGUAGES,),
    105: (_UZBEK,),
    106: (_HUMANITIES,),
    107: (_IT, _HUMANITIES),  # Informatics is taught by halves
    108: (_IT,),
}


@dataclass(frozen=True, slots=True)
class FakeStudent:
    """One student of the fake EMIS (names as EMIS sends them: Latin upper case)."""

    login: str
    emis_student_id: int
    first_name: str
    last_name: str
    middle_name: str
    group_emis_id: int
    group_name: str  # as in EMIS, Cyrillic
    current_semester: int
    curriculum_id: int

    @property
    def half(self) -> int:
        """Which half of the group: odd login numbers are 1, even ones 2."""
        return 1 if int(self.login.removeprefix("student")) % 2 else 2


def _build_students() -> tuple[FakeStudent, ...]:
    students = []
    for index in range(30):
        second_year = index < 15
        students.append(
            FakeStudent(
                login=f"student{index + 1:02d}",
                emis_student_id=78201 + index,
                first_name=_NAMES[index],
                last_name=_SURNAMES[index],
                middle_name=_PATRONYMICS[index % len(_PATRONYMICS)],
                group_emis_id=3292 if second_year else 3291,
                group_name="2ТН2" if second_year else "1ТН1",
                current_semester=3 if second_year else 1,
                curriculum_id=2124 if second_year else 2123,
            )
        )
    return tuple(students)


FAKE_STUDENTS: tuple[FakeStudent, ...] = _build_students()
_BY_LOGIN = {student.login: student for student in FAKE_STUDENTS}


def fake_curriculum_result() -> dict[str, Any]:
    """The ``result`` object of the fake ``curriculum/`` response (a fresh copy)."""
    result: dict[str, Any] = json.loads(FAKE_CURRICULUM_PATH.read_text("utf-8"))
    return result


@cache
def _base_curriculum() -> EmisCurriculum:
    """The sample file through the same DTO and mapping the real client uses."""
    return to_curriculum(CurriculumV1DTO.model_validate(fake_curriculum_result()))


def _next_year(text: str | None) -> str | None:
    """Add one to every four-digit year in the text: 2025-2027 becomes 2026-2028."""
    if text is None:
        return None
    return re.sub(r"\d{4}", lambda match: str(int(match.group()) + 1), text)


def _a_year_later(day: date | None) -> date | None:
    return None if day is None else day.replace(year=day.year + 1)


def _shifted(year: EmisYear | None) -> EmisYear | None:
    if year is None:
        return None
    return EmisYear(
        code=_next_year(year.code),
        name=_next_year(year.name),
        from_date=_a_year_later(year.from_date),
        to_date=_a_year_later(year.to_date),
    )


def fake_curriculum(curriculum_id: int) -> EmisCurriculum:
    """The curriculum of a group: the sample (2025-2027) for its own id, 2124.

    The other group (the first-year one, 2123) studies a year later than the sample,
    so its name and years are the sample's plus one and its semester dates are 52
    weeks later (the same weekdays).
    """
    base = _base_curriculum()
    if curriculum_id == base.emis_id:
        return base
    return replace(
        base,
        emis_id=curriculum_id,
        name=_next_year(base.name) or "",
        start_year=_shifted(base.start_year),
        end_year=_shifted(base.end_year),
        semesters=tuple(
            EmisSemesterDates(
                item.number,
                item.starts_on + _YEAR,
                item.ends_on + _YEAR,
            )
            for item in base.semesters
        ),
    )


def _cells_of(group_emis_id: int) -> list[Cell]:
    return cells_of(group_emis_id, FAKE_SUBJECTS, _TEACHERS_OF)


def _semester_window(current: int, semester: int) -> tuple[date, date]:
    start = _SEMESTER_START - _SEMESTER_GAP * (current - semester)
    return start, start + _SEMESTER_LENGTH


class FakeEmisClient:
    """Same interface as EmisClient; marks follow the injected clock."""

    def __init__(self, clock: Clock) -> None:
        """Store the clock that defines the fake "today"."""
        self._clock = clock

    async def aclose(self) -> None:
        """Nothing to close."""

    async def login(self, login: str, password: str) -> str:
        """Accept ``studentNN`` with the password ``password``."""
        name = login.strip().lower()
        if name == "down":
            raise EmisRequestError("fake EMIS is down")
        if name not in _BY_LOGIN or password != FAKE_PASSWORD:
            raise EmisAuthError()
        return f"{_TOKEN_PREFIX}{name}"

    def _student(self, token: str) -> FakeStudent:
        login = token.removeprefix(_TOKEN_PREFIX)
        student = _BY_LOGIN.get(login)
        if not token.startswith(_TOKEN_PREFIX) or student is None:
            raise EmisAuthError()
        return student

    async def profile(self, token: str) -> EmisProfile:
        """Return the profile of the token's student."""
        student = self._student(token)
        return EmisProfile(
            emis_student_id=student.emis_student_id,
            first_name=title_case(student.first_name),
            last_name=title_case(student.last_name),
            middle_name=title_case(student.middle_name),
            institution_id=FAKE_INSTITUTION_ID,
            group_emis_id=student.group_emis_id,
            group_name=normalize_group_name(student.group_name),
            current_semester=student.current_semester,
            curriculum_id=student.curriculum_id,
        )

    async def curriculum(self, token: str) -> list[EmisSubject]:
        """Return the same 8 subjects for everyone (from the sample curriculum)."""
        self._student(token)
        return curriculum_subjects(_base_curriculum())

    async def curriculum_detail(self, token: str) -> EmisCurriculum:
        """Return the student's group curriculum, built from the sample file."""
        return fake_curriculum(self._student(token).curriculum_id)

    async def ratings(
        self, token: str, subject_id: int, semester: int
    ) -> EmisSubjectRatings:
        """Return deterministic marks from the semester start up to today."""
        student = self._student(token)
        marks = self._marks(student, subject_id, semester)
        lesson_values = [m.value for m in marks if m.type is EmisMarkType.LESSON]
        rating = (
            round(sum(lesson_values) / len(lesson_values)) if lesson_values else None
        )
        digest = payload_hash(
            {
                "subject": subject_id,
                "semester": semester,
                "marks": [[m.type.value, m.date.isoformat(), m.value] for m in marks],
            }
        )
        return EmisSubjectRatings(
            emis_subject_id=subject_id,
            semester=semester,
            semester_rating=rating,
            marks=tuple(marks),
            payload_hash=digest,
        )

    async def class_hours(self, token: str) -> list[EmisClassHour]:
        """Return the five bells of the real ``class-hours`` response."""
        self._student(token)
        return list(FAKE_CLASS_HOURS)

    async def timetable(
        self, token: str, begin: dt.date, end: dt.date
    ) -> list[EmisClass]:
        """Return the classes on begin..end: the real response shape, week by week."""
        student = self._student(token)
        cells = _cells_of(student.group_emis_id)
        today = local_today(self._clock)
        classes: list[EmisClass] = []
        first = begin
        while first <= end:
            sunday = first + timedelta(days=7 - first.isoweekday())
            body = week_body(
                cells,
                student.group_emis_id,
                student.half,
                first,
                min(sunday, end),
                today,
            )
            classes.extend(to_classes(ClassSchedulesV1DTO.model_validate(body)))
            first = sunday + timedelta(days=1)
        return classes

    def _marks(
        self, student: FakeStudent, subject_id: int, semester: int
    ) -> list[EmisMark]:
        if semester > student.current_semester or semester < 1:
            return []
        start, end = _semester_window(student.current_semester, semester)
        today = local_today(self._clock)
        marks: list[EmisMark] = []
        day = start
        while day <= min(end, today):
            value = digest(student.login, subject_id, day.isoformat())
            if day.weekday() < 5 and value % 4 == 0:  # Monday to Friday
                marks.append(EmisMark(EmisMarkType.LESSON, day, 2 + (value >> 2) % 4))
            day += timedelta(days=1)
        if semester == student.current_semester and today >= _MIDTERM_DATE:
            value = digest(student.login, subject_id, "midterm")
            marks.append(EmisMark(EmisMarkType.MIDTERM, _MIDTERM_DATE, 3 + value % 3))
        return marks
