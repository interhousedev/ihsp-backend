"""Fake EMIS for ``EMIS__MODE=fake``: 30 students, 8 subjects, deterministic marks."""

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta

from app.modules.identity.application.register_models import (
    EmisAuthError,
    EmisRequestError,
)
from app.modules.identity.infrastructure.emis.mapping import payload_hash
from app.shared.clock import Clock, local_today
from app.shared.contracts.emis import (
    EmisMark,
    EmisMarkType,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
)
from app.shared.text import normalize_group_name, title_case

FAKE_PASSWORD = "password"
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


def _digest(*parts: object) -> int:
    raw = ":".join(str(part) for part in parts).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


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
        """Return the same 8 subjects for everyone."""
        self._student(token)
        return list(FAKE_SUBJECTS)

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
            value = _digest(student.login, subject_id, day.isoformat())
            if day.weekday() < 6 and value % 4 == 0:  # Monday to Saturday
                marks.append(EmisMark(EmisMarkType.LESSON, day, 2 + (value >> 2) % 4))
            day += timedelta(days=1)
        if semester == student.current_semester and today >= _MIDTERM_DATE:
            value = _digest(student.login, subject_id, "midterm")
            marks.append(EmisMark(EmisMarkType.MIDTERM, _MIDTERM_DATE, 3 + value % 3))
        return marks
