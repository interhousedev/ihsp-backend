"""CSV import of students: parsing and classification of rows (ACA-18)."""

import csv
import io
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.modules.academic.domain.schedule.errors import ImportInvalidError
from app.shared.text import normalize_group_name, title_case

REQUIRED_COLUMNS = ("last_name", "first_name", "group")
MAX_ROWS = 5000


class RowKind(StrEnum):
    """What the confirmation will do with a row."""

    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class CsvRow:
    """One normalized line of the file; ``error`` is set when it cannot be used."""

    line: int
    last_name: str
    first_name: str
    middle_name: str | None
    group_name: str
    emis_student_id: int | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class KnownStudent:
    """An existing student with the names loaded from the identity module."""

    user_id: UUID
    group_name: str
    first_name: str
    last_name: str
    middle_name: str | None


@dataclass(frozen=True, slots=True)
class ClassifiedRow:
    """A row with the decision for it."""

    row: CsvRow
    kind: RowKind
    user_id: UUID | None = None
    note: str | None = None


def normalize_name(value: str) -> str:
    """Title-case each word and each hyphenated part: "ABDUL-AZIZ" -> "Abdul-Aziz"."""
    words = value.split()
    return " ".join("-".join(title_case(part) for part in w.split("-")) for w in words)


def name_key(last_name: str, first_name: str) -> tuple[str, str]:
    """Return the case-insensitive key two people are matched by."""
    return " ".join(last_name.casefold().split()), " ".join(
        first_name.casefold().split()
    )


def _delimiter(header_line: str) -> str:
    return ";" if header_line.count(";") > header_line.count(",") else ","


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ImportInvalidError(params={"reason": "encoding"}) from error


def parse_csv(data: bytes) -> list[CsvRow]:
    """Read the file (UTF-8, comma or semicolon) into normalized rows."""
    text = _decode(data)
    first_line = text.split("\n", 1)[0]
    reader = csv.DictReader(io.StringIO(text), delimiter=_delimiter(first_line))
    fields = [(name or "").strip().lower() for name in reader.fieldnames or []]
    missing = [name for name in REQUIRED_COLUMNS if name not in fields]
    if missing:
        raise ImportInvalidError(params={"reason": "header", "missing": missing})
    reader.fieldnames = fields
    rows: list[CsvRow] = []
    for record in reader:
        if not any(isinstance(v, str) and v.strip() for v in record.values()):
            continue
        rows.append(_to_row(reader.line_num, record))
        if len(rows) > MAX_ROWS:
            raise ImportInvalidError(params={"reason": "too-many-rows"})
    return rows


def _cell(record: dict[str, str | None], name: str) -> str:
    return (record.get(name) or "").strip()


def _to_row(line: int, record: dict[str, str | None]) -> CsvRow:
    last = normalize_name(_cell(record, "last_name"))
    first = normalize_name(_cell(record, "first_name"))
    middle = normalize_name(_cell(record, "middle_name")) or None
    group = normalize_group_name(_cell(record, "group"))
    raw_id = _cell(record, "emis_student_id")
    error: str | None = None
    emis_id: int | None = None
    if not (last and first and group):
        error = "Last name, first name and group are required."
    elif raw_id:
        if raw_id.isdigit():
            emis_id = int(raw_id)
        else:
            error = "emis_student_id must be a number."
    return CsvRow(line, last, first, middle, group, emis_id, error)


def _middle_matches(row: CsvRow, known: KnownStudent) -> bool:
    if row.middle_name is None or known.middle_name is None:
        return True
    return row.middle_name.casefold() == known.middle_name.casefold()


def _duplicate_notes(rows: Sequence[CsvRow]) -> dict[int, str]:
    """Return a note for each line that repeats the name and group of an earlier one."""
    counts = Counter(
        (name_key(r.last_name, r.first_name), r.group_name)
        for r in rows
        if r.error is None
    )
    first_line: dict[tuple[tuple[str, str], str], int] = {}
    notes: dict[int, str] = {}
    for row in rows:
        key = (name_key(row.last_name, row.first_name), row.group_name)
        if row.error is not None or counts[key] < 2:
            continue
        first_line.setdefault(key, row.line)
        notes[row.line] = f"Same student as line {first_line[key]} in {row.group_name}."
    return notes


def _classify_one(
    row: CsvRow, index: dict[tuple[str, str], list[KnownStudent]]
) -> ClassifiedRow:
    candidates = [
        known
        for known in index.get(name_key(row.last_name, row.first_name), [])
        if _middle_matches(row, known)
    ]
    same_group = [k for k in candidates if k.group_name == row.group_name]
    if len(same_group) == 1:
        return ClassifiedRow(row, RowKind.UNCHANGED, same_group[0].user_id)
    if len(same_group) > 1:
        return ClassifiedRow(row, RowKind.CONFLICT, None, "Matches several students.")
    if len(candidates) == 1:
        note = f"Moves from {candidates[0].group_name}."
        return ClassifiedRow(row, RowKind.CHANGED, candidates[0].user_id, note)
    if len(candidates) > 1:
        return ClassifiedRow(row, RowKind.CONFLICT, None, "Matches several students.")
    return ClassifiedRow(row, RowKind.NEW)


def classify_rows(
    rows: Sequence[CsvRow], known: Sequence[KnownStudent]
) -> list[ClassifiedRow]:
    """Decide new / changed / unchanged / conflict for every row."""
    index: dict[tuple[str, str], list[KnownStudent]] = defaultdict(list)
    for student in known:
        index[name_key(student.last_name, student.first_name)].append(student)
    duplicates = _duplicate_notes(rows)
    result: list[ClassifiedRow] = []
    for row in rows:
        if row.error is not None:
            result.append(ClassifiedRow(row, RowKind.CONFLICT, None, row.error))
        elif row.line in duplicates:
            result.append(
                ClassifiedRow(row, RowKind.CONFLICT, None, duplicates[row.line])
            )
        else:
            result.append(_classify_one(row, index))
    return _flag_double_moves(result)


def _flag_double_moves(rows: list[ClassifiedRow]) -> list[ClassifiedRow]:
    """Two rows that would move the same existing student are both conflicts."""
    moved = Counter(r.user_id for r in rows if r.kind == RowKind.CHANGED)
    flagged: list[ClassifiedRow] = []
    for item in rows:
        if item.kind == RowKind.CHANGED and moved[item.user_id] > 1:
            flagged.append(
                ClassifiedRow(
                    item.row,
                    RowKind.CONFLICT,
                    None,
                    "Student appears in several groups.",
                )
            )
        else:
            flagged.append(item)
    return flagged
