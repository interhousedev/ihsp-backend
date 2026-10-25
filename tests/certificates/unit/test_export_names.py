"""Names inside the export archive."""

from app.modules.certificates.domain.export_names import (
    NameDeduper,
    archive_name,
    sanitize,
)


def test_a_name_is_group_student_filename() -> None:
    """The three parts are joined with dashes."""
    assert archive_name("2TN1", "Ann Alpha", "ielts.pdf") == "2TN1-Ann Alpha-ielts.pdf"


def test_separators_and_control_characters_are_removed() -> None:
    """Nothing in a part can walk out of the archive folder."""
    assert sanitize("../etc/passwd\x00") == "etc passwd"
    assert archive_name("2/TN", "A:B", "..\\x.pdf") == "2 TN-A B-x.pdf"


def test_repeated_names_are_numbered_before_the_extension() -> None:
    """The second and third get (2) and (3), ignoring case."""
    namer = NameDeduper()

    names = [namer.unique(n) for n in ("a-b-c.pdf", "A-B-C.pdf", "a-b-c.pdf")]

    assert names == ["a-b-c.pdf", "A-B-C (2).pdf", "a-b-c (3).pdf"]
