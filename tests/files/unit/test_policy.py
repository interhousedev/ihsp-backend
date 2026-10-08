"""FILE-2, FILE-4, FILE-5: what an upload may be."""

from datetime import UTC, date, datetime
from uuid import UUID

from app.modules.files.domain import policy
from app.modules.files.domain.errors import (
    FileTooLargeError,
    InvalidChecksumError,
    InvalidFileNameError,
    InvalidSizeError,
    TypeNotAllowedError,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FileScope
from tests.files.helpers import DOCX_TYPE, PDF_TYPE, sha256_b64

import pytest


@pytest.mark.parametrize(
    ("name", "declared"),
    [
        ("a.pdf", "application/pdf"),
        ("a.PDF", "application/pdf"),
        ("a.docx", DOCX_TYPE),
        (
            "a.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        (
            "a.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        ("a.txt", "text/plain"),
        ("a.txt", "text/plain; charset=utf-8"),
        ("a.md", "text/markdown"),
        ("a.md", ""),
        ("a.md", "application/octet-stream"),
        ("a.png", "image/png"),
        ("a.jpg", "image/jpeg"),
        ("a.jpeg", "image/jpeg"),
    ],
)
def test_allowed_extension_with_matching_declared_type_is_accepted(
    name: str, declared: str
) -> None:
    """FILE-4: PDF, DOCX, PPTX, XLSX, TXT, MD, PNG, JPG."""
    rule, signed = policy.check_declared(name, declared)

    assert signed in rule.declared or signed == rule.canonical


@pytest.mark.parametrize(
    ("name", "declared"),
    [
        ("virus.exe", "application/x-msdownload"),
        ("archive.zip", "application/zip"),
        ("old.doc", "application/msword"),
        ("page.html", "text/html"),
        ("image.svg", "image/svg+xml"),
        ("noextension", "application/pdf"),
        ("a.pdf", "image/png"),
        ("a.pdf", ""),
        ("a.docx", "application/octet-stream"),
        ("a.png", "application/pdf"),
    ],
)
def test_other_extensions_and_inconsistent_declared_types_are_refused(
    name: str, declared: str
) -> None:
    """FILE-4: ``.exe`` and friends are refused; the declared type must fit."""
    with pytest.raises(TypeNotAllowedError):
        policy.check_declared(name, declared)


def test_text_files_may_arrive_without_a_usable_content_type() -> None:
    """Browsers send an empty type for ``.md``: we sign the canonical one."""
    _, signed = policy.check_declared("notes.md", "")

    assert signed == "text/markdown"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("C:\\Users\\me\\report.pdf", "report.pdf"),
        ("  spaced name.pdf  ", "spaced name.pdf"),
        ("bad\x00name\n.pdf", "badname.pdf"),
    ],
)
def test_names_lose_paths_and_control_characters(raw: str, expected: str) -> None:
    """FILE-2: the stored name is a plain file name."""
    assert policy.normalize_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "..", ".", "a/", "x" * 256 + ".pdf"])
def test_empty_or_too_long_names_are_refused(raw: str) -> None:
    """Names are 1 to 255 characters."""
    with pytest.raises(InvalidFileNameError):
        policy.normalize_name(raw)


def test_name_of_255_characters_is_accepted() -> None:
    """The limit is inclusive."""
    name = "x" * 251 + ".pdf"

    assert policy.normalize_name(name) == name


def test_size_must_be_positive_and_within_the_per_file_limit() -> None:
    """FILE-4: up to 100 MB per file."""
    limit = 100 * 1024 * 1024

    policy.check_size(1, limit)
    policy.check_size(limit, limit)
    with pytest.raises(InvalidSizeError):
        policy.check_size(0, limit)
    with pytest.raises(FileTooLargeError):
        policy.check_size(limit + 1, limit)


def test_checksum_must_be_base64_of_32_bytes() -> None:
    """FILE-2: SHA-256 as base64 of the raw digest."""
    good = sha256_b64(b"hello")

    assert policy.check_checksum(good) == good
    for bad in ["", "not base64!", "AAAA", good.rstrip("=")]:
        with pytest.raises(InvalidChecksumError):
            policy.check_checksum(bad)


def test_students_without_a_staff_role_use_the_student_scope() -> None:
    """FILE-5: students 1.5 GB per term, staff 10 GB."""
    user = UUID(int=1)

    def actor(*roles: Role) -> Actor:
        return Actor(user_id=user, roles=frozenset(roles))

    assert policy.scope_for(actor(Role.STUDENT)) == FileScope.STUDENT
    assert policy.scope_for(actor(Role.TEACHER)) == FileScope.STAFF
    assert policy.scope_for(actor(Role.STUDENT, Role.TEACHER)) == FileScope.STAFF
    assert policy.scope_for(actor(Role.ADMIN)) == FileScope.STAFF
    assert policy.scope_for(actor(Role.LMS_ADMIN)) == FileScope.STAFF


def test_keys_are_built_from_scope_label_id_and_extension_only() -> None:
    """README -> File storage: ``{scope}/{term or yyyy-mm}/{uuid}.{ext}``."""
    file_id = UUID("0192f3c4-0000-7000-8000-000000000001")

    key = policy.key_for(FileScope.STUDENT, "2026-1", file_id, ".pdf")

    assert key == f"student/2026-1/{file_id}.pdf"
    assert policy.month_label(datetime(2026, 10, 6, 9, tzinfo=UTC)) == "2026-10"


def test_key_extension_never_carries_user_text() -> None:
    """Keys are random; only a short alphanumeric extension is kept."""
    assert policy.key_extension("a.PDF") == ".pdf"
    assert policy.key_extension("a.tar.gz") == ".gz"
    assert policy.key_extension("a.<script>") == ""
    assert policy.key_extension("noext") == ""


def test_only_pdf_and_images_may_open_inline() -> None:
    """FILE-3: everything else is downloaded."""
    assert policy.inline_allowed(PDF_TYPE)
    assert policy.inline_allowed("image/png")
    assert policy.inline_allowed("image/jpeg")
    assert not policy.inline_allowed("text/html")
    assert not policy.inline_allowed("image/svg+xml")
    assert not policy.inline_allowed(DOCX_TYPE)


def test_a_pdf_must_look_like_a_pdf_to_libmagic() -> None:
    """FILE-2: the sniffed type must fit the extension."""
    rule = policy.RULES[".pdf"]

    assert policy.detected_matches(rule, "application/pdf", b"%PDF-1.7")
    assert not policy.detected_matches(rule, "image/png", b"\x89PNG")
    assert not policy.detected_matches(rule, "text/plain", b"hello")


def test_ooxml_files_accept_zip_answers_only_with_the_zip_signature() -> None:
    """libmagic sometimes says zip or octet-stream for a DOCX header."""
    rule = policy.RULES[".docx"]

    assert policy.detected_matches(rule, DOCX_TYPE, b"PK\x03\x04")
    assert policy.detected_matches(rule, "application/zip", b"PK\x03\x04...")
    assert not policy.detected_matches(rule, "application/zip", b"MZ....")
    assert not policy.detected_matches(rule, "application/pdf", b"%PDF-")


def test_text_files_accept_any_text_type() -> None:
    """A Markdown file may be sniffed as text/x-something."""
    rule = policy.RULES[".md"]

    assert policy.detected_matches(rule, "text/plain", b"# hi")
    assert policy.detected_matches(rule, "text/x-script.python", b"print(1)")
    assert not policy.detected_matches(rule, "application/x-dosexec", b"MZ")


def test_student_files_expire_14_days_after_the_term_ends() -> None:
    """FILE-6, UF-SYS-07: delete after the expiry day, warn 7 days before."""
    end = date(2027, 1, 15)

    assert policy.expiry_date(end) == date(2027, 1, 29)
    assert not policy.is_term_expired(end, date(2027, 1, 29))
    assert policy.is_term_expired(end, date(2027, 1, 30))
    assert not policy.in_warning_window(end, date(2027, 1, 21))
    assert policy.in_warning_window(end, date(2027, 1, 22))
    assert policy.in_warning_window(end, date(2027, 1, 29))
    assert not policy.in_warning_window(end, date(2027, 1, 30))
