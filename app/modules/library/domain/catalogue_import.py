"""Bulk import of books from a CSV (doc § 3.4): one row per book.

Columns (header row, any order; lists use `|`; booleans `yes/no`, `true/false`, `1/0`):
`file_name`, `title`, `subtitle`, `authors`, `translators`, `language`,
`year_published`, `publisher`, `isbn`, `type`, `description`, `years_of_study`,
`subjects` (names or ids, `name:role` sets the role), `topics` (`topic_id` or
`topic_id:first-last` pages), `rights`, `licence`, `author_death_year`,
`first_published_year`, `rule`, `source_url`, `attribution`, `permission_scope`,
`permission_expires_on`, `reference`, `visibility`, `download_allowed`.
Rows are numbered like a spreadsheet: the header is row 1.
"""

import csv
import io
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from app.modules.library.domain.catalogue_books import BookData
from app.modules.library.domain.catalogue_errors import ImportInvalidError
from app.modules.library.domain.entities import SubjectLink, TopicLink
from app.modules.library.domain.enums import (
    ItemLanguage,
    ItemType,
    Rights,
    SubjectRole,
    Visibility,
)

from pydantic import ValidationError

MAX_ROWS = 500
MAX_CSV_BYTES = 2_000_000
LIST_SEPARATOR = "|"
_TRUE = frozenset({"1", "yes", "true", "y", "ha", "да"})
_BASIS_NUMBERS = ("author_death_year", "first_published_year")
_BASIS_TEXT = (
    "rule",
    "source_url",
    "attribution",
    "permission_scope",
    "permission_expires_on",
    "reference",
)
_REQUIRED = ("title",)


class ProblemCode(StrEnum):
    """Why a row was not imported; the use case turns it into a message."""

    MISSING_FIELD = "missing-field"
    BAD_VALUE = "bad-value"
    UNKNOWN_SUBJECT = "unknown-subject"
    FILE_NOT_FOUND = "file-not-found"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class RowProblem:
    """A row that cannot become a draft."""

    row: int
    code: ProblemCode
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImportRow:
    """A good row: the book data and the name of the file to attach, if any."""

    row: int
    data: BookData
    file_name: str | None


@dataclass(frozen=True, slots=True)
class ParsedCsv:
    """The outcome of reading the whole file."""

    rows: list[ImportRow]
    problems: list[RowProblem]


class _RowError(Exception):
    """Internal: a problem found while converting one row."""

    def __init__(self, code: ProblemCode, **params: str) -> None:
        super().__init__(code.value)
        self.code = code
        self.params = params


def parse_books_csv(text: str, *, subjects: Mapping[str, UUID]) -> ParsedCsv:
    """Read the CSV; `subjects` maps lower-cased names and ids to subject ids."""
    if len(text.encode()) > MAX_CSV_BYTES:
        raise ImportInvalidError(support_details="csv too large")
    sample = text.splitlines()[0] if text.strip() else ""
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=delimiter)
    header = {name.strip().lower() for name in reader.fieldnames or [] if name}
    if not set(_REQUIRED) <= header:
        raise ImportInvalidError(
            params={"missing": ", ".join(sorted(set(_REQUIRED) - header))},
            support_details="header lacks required columns",
        )
    rows: list[ImportRow] = []
    problems: list[RowProblem] = []
    for number, raw in enumerate(reader, start=2):
        if number - 1 > MAX_ROWS:
            raise ImportInvalidError(support_details=f"more than {MAX_ROWS} rows")
        values = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(values.values()):
            continue
        try:
            rows.append(_to_row(number, values, subjects))
        except _RowError as error:
            problems.append(RowProblem(number, error.code, error.params))
    return ParsedCsv(rows, problems)


def _to_row(
    number: int, values: Mapping[str, str], subjects: Mapping[str, UUID]
) -> ImportRow:
    for column in _REQUIRED:
        if not values.get(column):
            raise _RowError(ProblemCode.MISSING_FIELD, field=column)
    try:
        data = BookData(
            title=values["title"],
            subtitle=values.get("subtitle") or None,
            authors=_list(values.get("authors")),
            translators=_list(values.get("translators")),
            language=_enum(ItemLanguage, values, "language", ItemLanguage.UZ_LATN),
            year_published=_int(values, "year_published"),
            publisher=values.get("publisher") or None,
            isbn=values.get("isbn") or None,
            type=_enum(ItemType, values, "type", ItemType.OTHER),
            description=values.get("description") or None,
            years_of_study=_years(values.get("years_of_study")),
            subjects=_subjects(values.get("subjects"), subjects),
            topics=_topics(values.get("topics")),
            rights=_enum(Rights, values, "rights", Rights.OFFICIAL),
            licence=values.get("licence") or None,
            rights_basis=_basis(values),
            visibility=_enum(Visibility, values, "visibility", Visibility.LYCEUM),
            download_allowed=_flag(values.get("download_allowed")),
        )
    except ValidationError as error:
        first = error.errors()[0]
        field_name = ".".join(str(part) for part in first["loc"])
        raise _RowError(ProblemCode.INVALID, field=field_name) from error
    return ImportRow(number, data, values.get("file_name") or None)


def _list(value: str | None) -> list[str]:
    return [
        part.strip() for part in (value or "").split(LIST_SEPARATOR) if part.strip()
    ]


def _int(values: Mapping[str, str], column: str) -> int | None:
    raw = values.get(column)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise _RowError(ProblemCode.BAD_VALUE, field=column, value=raw) from error


def _years(raw: str | None) -> list[int]:
    try:
        return [int(year) for year in _list(raw)]
    except ValueError as error:
        raise _RowError(
            ProblemCode.BAD_VALUE, field="years_of_study", value=raw or ""
        ) from error


def _flag(raw: str | None) -> bool:
    return (raw or "").strip().lower() in _TRUE


def _enum[E: StrEnum](
    kind: type[E], values: Mapping[str, str], column: str, default: E | None
) -> E:
    raw = values.get(column, "").strip().lower()
    if not raw:
        if default is None:
            raise _RowError(ProblemCode.MISSING_FIELD, field=column)
        return default
    try:
        return kind(raw)
    except ValueError as error:
        raise _RowError(ProblemCode.BAD_VALUE, field=column, value=raw) from error


def _basis(values: Mapping[str, str]) -> dict[str, object]:
    basis: dict[str, object] = {}
    for column in _BASIS_NUMBERS:
        number = _int(values, column)
        if number is not None:
            basis[column] = number
    for column in _BASIS_TEXT:
        if values.get(column):
            basis[column] = values[column]
    return basis


def _subjects(raw: str | None, known: Mapping[str, UUID]) -> list[SubjectLink]:
    links: list[SubjectLink] = []
    for token in _list(raw):
        name, _, role = token.partition(":")
        subject_id = known.get(name.strip().lower())
        if subject_id is None:
            raise _RowError(ProblemCode.UNKNOWN_SUBJECT, value=name)
        try:
            subject_role = (
                SubjectRole(role.strip().lower()) if role else SubjectRole.SUPPLEMENTARY
            )
        except ValueError as error:
            raise _RowError(
                ProblemCode.BAD_VALUE, field="subjects", value=role
            ) from error
        links.append(SubjectLink(subject_id, subject_role))
    return links


def _topics(raw: str | None) -> list[TopicLink]:
    links: list[TopicLink] = []
    for position, token in enumerate(_list(raw)):
        topic, _, pages = token.partition(":")
        first, _, last = pages.partition("-")
        try:
            links.append(
                TopicLink(
                    UUID(topic.strip()),
                    int(first) if first else None,
                    int(last) if last else None,
                    position,
                )
            )
        except ValueError as error:
            raise _RowError(
                ProblemCode.BAD_VALUE, field="topics", value=token
            ) from error
    return links
