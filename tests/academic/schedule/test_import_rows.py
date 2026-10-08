"""CSV import of students: parsing and classifying rows (ADM-17, ACA-18, UF-ADM-14)."""

from uuid import UUID

from app.modules.academic.domain.schedule.errors import ImportInvalidError
from app.modules.academic.domain.schedule.import_rows import (
    KnownStudent,
    RowKind,
    classify_rows,
    parse_csv,
)
from app.shared.ids import new_id

import pytest

HEADER = "last_name,first_name,middle_name,group,emis_student_id\n"


def known(
    last: str,
    first: str,
    group: str,
    *,
    middle: str | None = None,
    user_id: UUID | None = None,
) -> KnownStudent:
    """An existing student."""
    return KnownStudent(user_id or new_id(), group, first, last, middle)


def test_rows_are_normalized() -> None:
    """ACA-1: names are title-cased and group names become Latin upper case."""
    rows = parse_csv((HEADER + "BRASTILOV,ALEKSEY,SERGEEVICH,2ТН2,12345\n").encode())

    assert len(rows) == 1
    row = rows[0]
    assert (row.last_name, row.first_name, row.middle_name) == (
        "Brastilov",
        "Aleksey",
        "Sergeevich",
    )
    assert row.group_name == "2TN2"
    assert row.emis_student_id == 12345
    assert row.line == 2 and row.error is None


def test_semicolon_delimiter_and_bom_are_detected() -> None:
    """ADM-17: EMIS exports open in Excel with ; and a BOM."""
    data = (
        "﻿last_name;first_name;middle_name;group;emis_student_id\nIvanov;Ivan;;2TN1;\n"
    )

    rows = parse_csv(data.encode("utf-8"))

    assert [
        (r.last_name, r.group_name, r.middle_name, r.emis_student_id) for r in rows
    ] == [("Ivanov", "2TN1", None, None)]


def test_hyphenated_names_keep_their_capitals() -> None:
    """Names such as Abdul-Aziz are title-cased by part."""
    rows = parse_csv((HEADER + "ABDUL-AZIZ,SHAKHZOD,,2TN1,\n").encode())

    assert rows[0].last_name == "Abdul-Aziz"


def test_blank_lines_are_skipped_but_line_numbers_stay_true() -> None:
    """UF-ADM-14: the preview points at the line in the file."""
    rows = parse_csv((HEADER + "\nIvanov,Ivan,,2TN1,\n").encode())

    assert [r.line for r in rows] == [3]


def test_a_missing_required_column_is_rejected() -> None:
    """ADM-17: the header must contain last_name, first_name and group."""
    with pytest.raises(ImportInvalidError) as caught:
        parse_csv(b"last_name,first_name\nIvanov,Ivan\n")

    assert caught.value.params["missing"] == ["group"]


def test_a_file_that_is_not_utf8_is_rejected() -> None:
    """ADM-17: UTF-8 only."""
    with pytest.raises(ImportInvalidError):
        parse_csv("last_name,first_name,group\nИванов,Иван,2ТН1\n".encode("cp1251"))


def test_incomplete_and_malformed_rows_are_conflicts_with_a_note() -> None:
    """UF-ADM-14 2a: rows that match nobody are shown for correction."""
    rows = parse_csv((HEADER + ",Ivan,,2TN1,\nPetrov,Petr,,2TN1,abc\n").encode())

    result = classify_rows(rows, [])

    assert [r.kind for r in result] == [RowKind.CONFLICT, RowKind.CONFLICT]
    assert all(r.note for r in result)


def test_unknown_students_are_new() -> None:
    """UF-ADM-14: nobody with this name in the group means a new profile."""
    rows = parse_csv((HEADER + "Ivanov,Ivan,,2TN1,\n").encode())

    result = classify_rows(rows, [known("Petrov", "Petr", "2TN1")])

    assert [r.kind for r in result] == [RowKind.NEW]


def test_a_student_with_the_same_name_in_the_same_group_is_unchanged() -> None:
    """UF-ADM-14: re-importing the same export changes nothing; case is ignored."""
    existing = known("Ivanov", "Ivan", "2TN1")
    rows = parse_csv((HEADER + "IVANOV,ivan,,2TN1,\n").encode())

    result = classify_rows(rows, [existing])

    assert [(r.kind, r.user_id) for r in result] == [
        (RowKind.UNCHANGED, existing.user_id)
    ]


def test_a_student_found_in_another_group_is_changed() -> None:
    """UF-ADM-14: the student moved to another group."""
    existing = known("Ivanov", "Ivan", "2TN2")
    rows = parse_csv((HEADER + "Ivanov,Ivan,,2TN1,\n").encode())

    result = classify_rows(rows, [existing])

    assert result[0].kind == RowKind.CHANGED
    assert result[0].user_id == existing.user_id
    assert "2TN2" in (result[0].note or "")


def test_two_rows_for_the_same_student_in_a_group_are_both_conflicts() -> None:
    """UF-ADM-14 2a: duplicates are resolved by the admin before importing."""
    rows = parse_csv((HEADER + "Ivanov,Ivan,,2TN1,\nIVANOV,IVAN,,2TN1,\n").encode())

    result = classify_rows(rows, [])

    assert [r.kind for r in result] == [RowKind.CONFLICT, RowKind.CONFLICT]


def test_a_name_matching_two_students_is_a_conflict() -> None:
    """UF-ADM-14 2a: ambiguous matches are not guessed."""
    twins = [known("Ivanov", "Ivan", "2TN1"), known("Ivanov", "Ivan", "2TN1")]
    rows = parse_csv((HEADER + "Ivanov,Ivan,,2TN1,\n").encode())

    assert classify_rows(rows, twins)[0].kind == RowKind.CONFLICT


def test_middle_names_tell_namesakes_apart() -> None:
    """UF-ADM-14: when both sides have a middle name it must match."""
    first = known("Ivanov", "Ivan", "2TN1", middle="Petrovich")
    second = known("Ivanov", "Ivan", "2TN1", middle="Sergeevich")
    rows = parse_csv((HEADER + "Ivanov,Ivan,Sergeevich,2TN1,\n").encode())

    result = classify_rows(rows, [first, second])

    assert [(r.kind, r.user_id) for r in result] == [
        (RowKind.UNCHANGED, second.user_id)
    ]


def test_one_student_in_two_groups_of_the_file_is_flagged() -> None:
    """UF-ADM-14: a person cannot be moved to two groups at once."""
    existing = known("Ivanov", "Ivan", "2TN3")
    rows = parse_csv((HEADER + "Ivanov,Ivan,,2TN1,\nIvanov,Ivan,,2TN2,\n").encode())

    result = classify_rows(rows, [existing])

    assert [r.kind for r in result] == [RowKind.CONFLICT, RowKind.CONFLICT]
