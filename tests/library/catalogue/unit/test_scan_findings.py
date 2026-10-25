"""LIB-13: personal data and exam-paper markers found in a material's text."""

from app.modules.library.domain.scan_findings import (
    FindingCode,
    personal_data_findings,
    scan_material_text,
)

import pytest


@pytest.mark.parametrize(
    "text",
    [
        "Call me: +998 90 123 45 67 after school",
        "tel 998901234567",
        "my number is 90-123-45-67",
        "(90) 123 45 67",
    ],
)
def test_uzbek_phone_numbers_are_found(text: str) -> None:
    """LIB-13: phone numbers in common spellings are flagged."""
    assert FindingCode.PHONE_NUMBER in personal_data_findings(text)


@pytest.mark.parametrize(
    "text",
    [
        "In 1969 the Moon landing happened, ISBN 978-9943-12-345-6",
        "The speed is 299792458 m/s",
        "Problem 12. Find 3.14159265 to six places",
    ],
)
def test_numbers_that_are_not_phones_are_not_flagged(text: str) -> None:
    """LIB-13: long numbers in a science text are not personal data."""
    assert FindingCode.PHONE_NUMBER not in personal_data_findings(text)


def test_email_addresses_are_found() -> None:
    """LIB-13: e-mails are personal data."""
    findings = personal_data_findings("Write to aziza.k@example.uz for answers")

    assert FindingCode.EMAIL in findings
    assert FindingCode.HANDLE not in findings


def test_social_handles_are_found() -> None:
    """LIB-13: an @handle is personal data, an e-mail domain is not a handle."""
    assert FindingCode.HANDLE in personal_data_findings("telegram: @aziza_k99")
    assert FindingCode.HANDLE not in personal_data_findings("a@b.com")


def test_clean_text_has_no_findings() -> None:
    """LIB-13: ordinary lecture notes produce nothing."""
    assert scan_material_text("Newton's second law: F = m a. See page 12.") == []


@pytest.mark.parametrize(
    "text",
    [
        "Oraliq nazorat savollari",
        "YAKUNIY NAZORAT 2025",
        "Рубежный контроль по физике",
        "Midterm exam, fall",
        "Final test",
        "Variant 3",
        "Вариант 2",
        "variant №7",
    ],
)
def test_exam_paper_markers_are_found(text: str) -> None:
    """LIB-13: markers of control papers are flagged for the librarian."""
    assert FindingCode.EXAM_MARKER in scan_material_text(text)


def test_cyrillic_uzbek_markers_are_found() -> None:
    """LIB-13: the same markers written in Uzbek Cyrillic."""
    assert FindingCode.EXAM_MARKER in scan_material_text("Оралиқ назорат")


def test_final_inside_another_word_is_not_a_marker() -> None:
    """LIB-13: only the whole word counts."""
    assert scan_material_text("Finally, the finalists agreed") == []


def test_findings_are_unique_and_ordered() -> None:
    """LIB-13: every code appears once, in a stable order."""
    text = "+998 90 123 45 67, +998 91 111 22 33, a@b.uz, Midterm, Final"

    assert scan_material_text(text) == [
        FindingCode.PHONE_NUMBER,
        FindingCode.EMAIL,
        FindingCode.EXAM_MARKER,
    ]
