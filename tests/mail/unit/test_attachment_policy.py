"""MAIL-2, FILE-4: which attachments are stored and forwarded."""

from app.modules.mail.domain.attachment_policy import (
    MAX_ATTACHMENT_BYTES,
    judge_attachment,
)
from tests.mail.helpers import PDF_BYTES, PNG_BYTES


def test_a_pdf_is_allowed() -> None:
    """MAIL-2: PDF with the right bytes."""
    assert judge_attachment("report.pdf", "application/pdf", PDF_BYTES).allowed


def test_octet_stream_with_a_known_extension_is_allowed() -> None:
    """MAIL-2: clients often send documents as octet-stream."""
    assert judge_attachment("a.png", "application/octet-stream", PNG_BYTES).allowed


def test_an_exe_is_skipped() -> None:
    """MAIL-2: types outside FILE-4 are only listed by name."""
    verdict = judge_attachment("setup.exe", "application/octet-stream", b"MZ\x90")

    assert not verdict.allowed
    assert verdict.reason == "type"


def test_a_pdf_name_with_exe_bytes_is_skipped() -> None:
    """MAIL-2: the content must agree with the name."""
    verdict = judge_attachment("invoice.pdf", "application/pdf", b"MZ\x90\x00")

    assert not verdict.allowed
    assert verdict.reason == "content"


def test_a_declared_type_that_disagrees_with_the_extension_is_skipped() -> None:
    """MAIL-2: .pdf declared as image/png."""
    assert not judge_attachment("a.pdf", "image/png", PDF_BYTES).allowed


def test_text_files_must_not_contain_nul_bytes() -> None:
    """MAIL-2: .txt/.md are text."""
    assert judge_attachment("notes.txt", "text/plain", b"hello").allowed
    assert not judge_attachment("notes.txt", "text/plain", b"he\x00llo").allowed


def test_office_files_are_zip_containers() -> None:
    """MAIL-2: docx/pptx/xlsx start with PK."""
    ooxml = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    assert judge_attachment("a.docx", ooxml, b"PK\x03\x04rest").allowed
    assert not judge_attachment("a.docx", ooxml, b"plain text").allowed


def test_a_file_over_fifty_megabytes_is_skipped() -> None:
    """MAIL-2: attachments up to 50 MB."""
    big = b"%PDF" + b"0" * MAX_ATTACHMENT_BYTES

    verdict = judge_attachment("big.pdf", "application/pdf", big)

    assert not verdict.allowed
    assert verdict.reason == "size"


def test_an_empty_attachment_is_skipped() -> None:
    """MAIL-2: nothing to forward."""
    assert not judge_attachment("a.pdf", "application/pdf", b"").allowed
