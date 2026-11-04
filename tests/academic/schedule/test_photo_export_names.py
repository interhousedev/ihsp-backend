"""ADM-PHOTO-1: file names of the group photo export are safe and unique."""

from app.modules.academic.domain.schedule.photo_export import (
    detect_photo_extension,
    full_name,
    safe_stem,
    unique_entry_names,
)

JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"0" * 16
PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def test_full_name_is_last_first_middle_and_skips_a_missing_middle_name() -> None:
    """ADM-PHOTO-1: the file is named after the student's full name."""
    assert full_name("Ivanov", "Ivan", "Ivanovich") == "Ivanov Ivan Ivanovich"
    assert full_name("Ivanov", "Ivan", None) == "Ivanov Ivan"
    assert full_name("Ivanov", "Ivan", "  ") == "Ivanov Ivan"


def test_cyrillic_and_uzbek_letters_are_kept() -> None:
    """ADM-PHOTO-1: Cyrillic and Uzbek letters, including the modifier apostrophe."""
    assert safe_stem("Қодиров Ўткир Ҳамидович") == "Қодиров Ўткир Ҳамидович"
    assert safe_stem("Toʼrayev Aziz") == "Toʼrayev Aziz"


def test_path_separators_and_traversal_are_removed() -> None:
    """ADM-PHOTO-1: a name cannot leave the archive root."""
    for hostile in ("../../etc/passwd", "..\\..\\boot.ini", "/abs/path", "a/../b"):
        stem = safe_stem(hostile)
        assert "/" not in stem
        assert "\\" not in stem
        assert ".." not in stem
        assert not stem.startswith(".")


def test_control_and_reserved_characters_are_removed() -> None:
    """ADM-PHOTO-1: control characters and characters Windows forbids go."""
    assert safe_stem("Ivanov\x00\r\n Ivan\t") == "Ivanov Ivan"
    assert safe_stem('Ivan<o>v: "x"|y?*') == "Ivan o v x y"


def test_an_empty_name_falls_back_to_a_given_default() -> None:
    """ADM-PHOTO-1: a name made only of junk still yields a usable file name."""
    assert safe_stem("  ../  ", fallback="student-1234") == "student-1234"


def test_a_long_name_is_cut_to_a_hundred_characters() -> None:
    """ADM-PHOTO-1: long names stay well under the zip and filesystem limits."""
    assert len(safe_stem("A" * 300)) == 100


def test_duplicate_names_get_a_numeric_suffix_case_insensitively() -> None:
    """ADM-PHOTO-1: two students with one name both keep their photo."""
    names = unique_entry_names(
        ["Ivanov Ivan.jpg", "Ivanov Ivan.jpg", "ivanov ivan.jpg"]
    )

    assert names == [
        "Ivanov Ivan.jpg",
        "Ivanov Ivan (2).jpg",
        "ivanov ivan (3).jpg",
    ]


def test_the_photo_format_comes_from_the_bytes_only() -> None:
    """ADM-PHOTO-1: JPEG and PNG by magic bytes; anything else is not exported."""
    assert detect_photo_extension(JPEG_HEAD) == "jpg"
    assert detect_photo_extension(PNG_HEAD) == "png"
    assert detect_photo_extension(b"<html>not a photo</html>") is None
    assert detect_photo_extension(b"") is None
