"""MagicSniffer against the real libmagic (a system library).

Skipped where libmagic is not installed (``brew install libmagic``, ``libmagic1``).
"""

from app.modules.files.domain import policy
from app.modules.files.ports.content_sniffer import ContentSniffer
from tests.files.helpers import (
    DOCX_TYPE,
    EXE_BYTES,
    PNG_BYTES,
    make_docx,
    make_epub,
    make_pdf,
    real_jpeg,
    real_png,
)

import pytest


@pytest.fixture
def sniffer() -> ContentSniffer:
    """The real sniffer; the test is skipped when libmagic is missing."""
    pytest.importorskip("magic", exc_type=ImportError)
    from app.modules.files.infrastructure.sniffing.magic_sniffer import MagicSniffer

    return MagicSniffer()


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("a.pdf", make_pdf("hello"), "application/pdf"),
        ("a.png", real_png(), "image/png"),
        ("a.jpg", real_jpeg(), "image/jpeg"),
        ("a.docx", make_docx("hello"), DOCX_TYPE),
        ("a.epub", make_epub(["<p>hello</p>"]), "application/epub+zip"),
        ("a.txt", "Привет, мир".encode(), "text/plain"),
        ("a.md", b"# Title\n\ntext", "text/plain"),
    ],
)
async def test_allowed_files_are_recognised_and_consistent_with_their_extension(
    sniffer: ContentSniffer, name: str, data: bytes, expected: str
) -> None:
    """libmagic and the policy agree for every allowed type (first 64 KiB)."""
    detected = await sniffer.sniff(data[: policy.SNIFF_BYTES])

    rule = policy.rule_for_name(name)
    assert rule is not None
    assert detected == expected or detected.startswith("text/")
    assert policy.detected_matches(rule, detected, data[:16])


async def test_an_executable_and_a_png_do_not_pass_as_pdf(
    sniffer: ContentSniffer,
) -> None:
    """The type-mismatch check on real libmagic answers."""
    rule = policy.RULES[".pdf"]

    for data in (EXE_BYTES, PNG_BYTES):
        detected = await sniffer.sniff(data)
        assert not policy.detected_matches(rule, detected, data)


async def test_a_docx_renamed_to_epub_does_not_pass_as_an_epub(
    sniffer: ContentSniffer,
) -> None:
    """The real type must fit the extension, also for zip-based formats."""
    rule = policy.RULES[".epub"]
    data = make_docx("hello")

    detected = await sniffer.sniff(data)

    assert not policy.detected_matches(rule, detected, data[:16])
