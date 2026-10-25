"""LIB-3: reading the CSV of a bulk import row by row."""

from uuid import UUID

from app.modules.library.domain.catalogue_errors import ImportInvalidError
from app.modules.library.domain.catalogue_import import (
    ProblemCode,
    parse_books_csv,
)
from app.modules.library.domain.enums import (
    ItemLanguage,
    Rights,
    SubjectRole,
    Visibility,
)
from app.shared.ids import new_id

import pytest

PHYSICS = new_id()
SUBJECTS = {"physics": PHYSICS, str(PHYSICS): PHYSICS}
HEADER = "file_name,title,authors,language,type,subjects,rights,reference,visibility"


def _csv(*rows: str, header: str = HEADER) -> str:
    return "\n".join([header, *rows]) + "\n"


def test_a_good_row_becomes_book_data_with_the_file_name() -> None:
    """LIB-3: metadata, rights basis and tags are read from the columns."""
    text = _csv(
        "physics10.pdf,Physics 10,A. Author|B. Author,uz_latn,textbook,"
        "Physics:textbook,official,Order 12,lyceum"
    )

    parsed = parse_books_csv(text, subjects=SUBJECTS)

    assert parsed.problems == []
    (row,) = parsed.rows
    assert row.row == 2 and row.file_name == "physics10.pdf"
    assert row.data.authors == ["A. Author", "B. Author"]
    assert row.data.language is ItemLanguage.UZ_LATN
    assert row.data.rights is Rights.OFFICIAL
    assert row.data.rights_basis == {"reference": "Order 12"}
    assert row.data.visibility is Visibility.LYCEUM
    assert [(s.subject_id, s.role) for s in row.data.subjects] == [
        (PHYSICS, SubjectRole.TEXTBOOK)
    ]


def test_bad_rows_are_listed_with_their_row_numbers_and_good_rows_stay() -> None:
    """LIB-3: rows are numbered like a spreadsheet (header is row 1)."""
    text = _csv(
        ",Good,A,uz_latn,textbook,physics,official,Order 1,lyceum",
        ",,A,uz_latn,textbook,physics,official,Order 1,lyceum",
        ",Unknown subject,A,uz_latn,textbook,chemistry,official,Order 1,lyceum",
        ",Bad rights,A,uz_latn,textbook,physics,sold,Order 1,lyceum",
        ",Bad language,A,klingon,textbook,physics,official,Order 1,lyceum",
    )

    parsed = parse_books_csv(text, subjects=SUBJECTS)

    assert [r.row for r in parsed.rows] == [2]
    assert [(p.row, p.code) for p in parsed.problems] == [
        (3, ProblemCode.MISSING_FIELD),
        (4, ProblemCode.UNKNOWN_SUBJECT),
        (5, ProblemCode.BAD_VALUE),
        (6, ProblemCode.BAD_VALUE),
    ]
    assert parsed.problems[0].params == {"field": "title"}


def test_semicolon_files_from_excel_and_a_bom_are_read() -> None:
    """LIB-3: Uzbek-locale spreadsheets export `;`."""
    text = "﻿title;rights;reference\nKitob;official;Order 1\n"

    parsed = parse_books_csv(text, subjects=SUBJECTS)

    assert [r.data.title for r in parsed.rows] == ["Kitob"]


def test_subjects_are_matched_by_id_and_case_insensitively() -> None:
    """LIB-3: names and ids both work."""
    text = _csv(f",Kitob,A,uz_latn,other,{PHYSICS},official,r,lyceum")

    parsed = parse_books_csv(text, subjects={"physics": PHYSICS, str(PHYSICS): PHYSICS})

    assert parsed.rows[0].data.subjects[0].subject_id == PHYSICS


def test_topics_take_an_optional_page_range() -> None:
    """LIB-3: `topic_id:10-20`."""
    topic, plain = new_id(), new_id()
    text = _csv(
        f",Kitob,A,uz_latn,other,,official,r,lyceum,{topic}:10-20|{plain}",
        header=HEADER + ",topics",
    )

    parsed = parse_books_csv(text, subjects=SUBJECTS)

    first, second = parsed.rows[0].data.topics
    assert (first.topic_id, first.page_from, first.page_to) == (topic, 10, 20)
    assert isinstance(second.topic_id, UUID) and second.page_from is None


def test_header_without_required_columns_is_refused() -> None:
    """LIB-3: `library/import-invalid` when `title` or `rights` is not a column."""
    with pytest.raises(ImportInvalidError):
        parse_books_csv("name,licence\nA,B\n", subjects=SUBJECTS)


def test_too_many_rows_are_refused() -> None:
    """LIB-3: at most 500 rows per import."""
    rows = [f"Kitob {n},official,r" for n in range(501)]

    with pytest.raises(ImportInvalidError):
        parse_books_csv("title,rights,reference\n" + "\n".join(rows), subjects=SUBJECTS)


def test_blank_lines_are_skipped() -> None:
    """LIB-3: empty rows are not errors."""
    text = "title,rights,reference\n,,\nKitob,official,r\n"

    parsed = parse_books_csv(text, subjects=SUBJECTS)

    assert [r.row for r in parsed.rows] == [3] and parsed.problems == []
