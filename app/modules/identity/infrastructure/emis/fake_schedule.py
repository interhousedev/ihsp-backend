"""The fake EMIS timetable: raw ``class-schedules`` bodies, exactly as EMIS sends them.

The fake client turns these bodies into contract objects with the same DTOs and mapper
as the real client, so the fake can never drift from the real shape. Odd and even weeks
alternate from ``WEEK_ANCHOR`` (the Monday before the demo term's first day); a student
sees only the slot of their own half in a class taught in halves.
"""

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from app.shared.contracts.emis import EmisSubject, EmisTeacher

WEEK_ANCHOR = date(2026, 8, 31)
MIDTERM_DAY = date(2026, 10, 20)
FINAL_DAY = date(2026, 12, 22)
_WEEKDAYS = (1, 2, 3, 4, 5)
_PAIRS_PER_DAY = 4
_ROOMS_OF = {3292: ("101", "204"), 3291: ("102", "Кластер")}
_CLASS_TYPES = {
    "lecture": (1, "Ma'ruza"),
    "practice": (2, "Amaliyot"),
    "midterm": (5, "Oraliq nazorat"),
    "final": (6, "Yakuniy nazorat"),
}

Parity = Literal["every", "odd", "even"]


@dataclass(frozen=True, slots=True)
class Cell:
    """One slot of a group's week: who teaches what where, for which half and weeks."""

    weekday: int
    pair: int
    subject: EmisSubject
    teacher: EmisTeacher
    room: str
    half: Literal[1, 2] | None = None
    parity: Parity = "every"


def digest(*parts: object) -> int:
    """A stable number from the parts (no randomness in the fake)."""
    raw = ":".join(str(part) for part in parts).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def is_odd_week(monday: date) -> bool:
    """Weeks count from ``WEEK_ANCHOR`` (week 1 is odd)."""
    return ((monday - WEEK_ANCHOR).days // 7) % 2 == 0


def cells_of(
    group_emis_id: int,
    subjects: tuple[EmisSubject, ...],
    teachers_of: dict[int, tuple[EmisTeacher, ...]],
) -> list[Cell]:
    """Four pairs a day, Monday to Friday; the lyceum does not study on Saturday."""
    rooms = _ROOMS_OF.get(group_emis_id)
    if rooms is None:
        return []
    shift = 0 if group_emis_id == 3292 else 3
    ordered = sorted(subjects, key=lambda subject: subject.emis_subject_id)
    cells: list[Cell] = []
    for weekday in _WEEKDAYS:
        for pair in range(_PAIRS_PER_DAY):
            subject = ordered[(weekday * _PAIRS_PER_DAY + pair + shift) % len(ordered)]
            teachers = teachers_of[subject.emis_subject_id]
            if len(teachers) == 2:
                cells.append(Cell(weekday, pair, subject, teachers[0], rooms[0], 1))
                cells.append(Cell(weekday, pair, subject, teachers[1], rooms[1], 2))
            else:
                cells.append(Cell(weekday, pair, subject, teachers[0], rooms[0]))
    return cells


def _kind_of(day: date, pair: int) -> str:
    if pair == 0 and day == MIDTERM_DAY:
        return "midterm"
    if pair == 0 and day == FINAL_DAY:
        return "final"
    return "lecture" if pair % 2 == 0 else "practice"


def _teacher_row(
    cell: Cell, day: date, group_emis_id: int, half: int, today: date
) -> dict[str, Any]:
    seed = digest(group_emis_id, day, cell.pair, cell.half)
    type_id, type_name = _CLASS_TYPES[_kind_of(day, cell.pair)]
    teacher = cell.teacher
    person = {
        "id": 40000 + (teacher.emis_id or 0),
        "birth_date": "04.01.1969",
        "first_name": teacher.first_name.upper(),
        "middle_name": (teacher.middle_name or "").upper() or None,
        "last_name": teacher.last_name.upper(),
        "gender_id": 1,
        "gender": "Erkak",
    }
    subject = cell.subject
    return {
        "id": 4_000_000 + seed % 900_000,
        "edu_subject_id": subject.emis_subject_id,
        "edu_subject": {
            "id": subject.emis_subject_id,
            "name": {
                "uz": subject.name_uz,
                "ru": subject.name_ru,
                "en": subject.name_en,
            },
            "status": "ACTIVE",
            "can_be_divided": cell.half is not None,
            "is_custom": False,
        },
        "class_type_id": type_id,
        "class_type": {"id": type_id, "name": type_name, "description": ""},
        "teacher_id": teacher.emis_id,
        "teacher": {"id": teacher.emis_id, "citizen": person, "status": "ACTIVE"},
        "room_id": 2000 + seed % 100,
        "room": {"id": 2000 + seed % 100, "name": cell.room, "capacity": 30},
        "pair_number": 0,  # EMIS repeats 0 here; the class's own pair_number counts
        "is_seperated": None,
        "group_number": half if cell.half is not None else 1,
        "topic_id": 0,
        "topic": _topic(cell, day, seed) if day <= today else None,
        "rating": None,
    }


def _topic(cell: Cell, day: date, seed: int) -> dict[str, Any]:
    """A topic with a file, a homework file and a video on some days, none on others."""
    base = f"https://cdn-emis.edu.uz/files/{seed:08x}"
    has_video = seed % 5 == 0
    return {
        "id": 1_000_000 + seed % 900_000,
        "name": f"{cell.subject.name_en}: lesson of {day.isoformat()}",
        "description": "Read the topic and prepare questions." if seed % 2 else "",
        "topic_file": f"{seed:08x}.pdf" if seed % 2 == 0 else None,
        "topic_file_url": f"{base}.pdf" if seed % 2 == 0 else None,
        "homework_file": f"{seed:08x}-hw.pdf" if seed % 3 == 0 else None,
        "homework_file_url": f"{base}-hw.pdf" if seed % 3 == 0 else "",
        "video_url": f"https://www.youtube.com/watch?v={seed:08x}" if has_video else "",
        "teacher_topic_id": 46000 + seed % 1000,
        "order_no": 1 + seed % 20,
    }


def _classes_on(
    day: date, cells: list[Cell], group_emis_id: int, half: int, today: date
) -> list[dict[str, Any]] | None:
    odd = is_odd_week(day - timedelta(days=day.weekday()))
    classes: list[dict[str, Any]] = []
    for cell in sorted(cells, key=lambda c: c.pair):
        if cell.weekday != day.isoweekday():
            continue
        if cell.parity != "every" and (cell.parity == "odd") != odd:
            continue
        if cell.half is not None and cell.half != half:
            continue  # the student only sees their own half
        seed = digest(group_emis_id, day, cell.pair, cell.half)
        classes.append(
            {
                "id": 3_000_000 + seed % 900_000,
                "is_seperated": cell.half is not None,
                "class_type_id": 0,
                "class_type": None,
                "edu_group_id": group_emis_id,
                "edu_group": None,
                "pair_number": cell.pair,
                "teachers": [_teacher_row(cell, day, group_emis_id, half, today)],
            }
        )
    return classes or None


def week_body(
    cells: list[Cell],
    group_emis_id: int,
    half: int,
    first: date,
    last: date,
    today: date,
) -> dict[str, Any]:
    """The body of one ``class-schedules`` request for the days first..last."""
    days = []
    day = first
    while day <= last:
        days.append(
            {
                "date": day.strftime("%d.%m.%Y"),
                "classes": _classes_on(day, cells, group_emis_id, half, today),
            }
        )
        day += timedelta(days=1)
    return {
        "results": days,
        "total_results": len(days),
        "total_pages": 1,
        "code": 200,
        "success": True,
        "error": None,
    }
