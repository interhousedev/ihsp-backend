"""Course certificates: tier evaluation and upload validation."""

import io
from decimal import Decimal
from uuid import uuid4

from app.modules.certificates.domain.course.rules import (
    CertificateSettings,
    SectionResult,
    default_fields,
    evaluate,
    parse_fields,
    parse_qr,
    parse_tiers,
)
from app.modules.certificates.domain.errors import (
    CertificateUploadRejectedError,
    CourseCertificateInvalidError,
)
from app.modules.certificates.infrastructure import course_render

import pytest
from PIL import Image


def section(sid: str, total: int, done: int, pts: int, earned: int) -> SectionResult:
    """A section result."""
    return SectionResult(sid, total, done, Decimal(pts), Decimal(earned))


def settings(**values: object) -> CertificateSettings:
    """Default tiers: normal (passing), honors (90), extra (90 + optional)."""
    return CertificateSettings(
        course_id=uuid4(), passing_pct=60, **values  # type: ignore[arg-type]
    )


def test_unfinished_required_section_is_not_eligible() -> None:
    """A missing required step blocks every tier."""
    result = evaluate(settings(), [section("a", 3, 2, 10, 10)])
    assert not result.passed and result.tier is None
    assert result.next_tier is not None and result.next_tier.key == "normal"


def test_score_below_passing_is_not_eligible() -> None:
    """All steps done but 50 % < 60 %."""
    result = evaluate(settings(), [section("a", 2, 2, 10, 5)])
    assert result.score_pct == 50 and not result.passed


def test_tiers_pick_the_highest_match() -> None:
    """75 % gives normal, 95 % honours, 95 % plus optional work extra."""
    s = settings(optional_section_ids=("opt",))
    normal = evaluate(s, [section("a", 2, 2, 100, 75), section("opt", 1, 0, 10, 0)])
    assert normal.tier is not None and normal.tier.key == "normal"
    assert normal.next_tier is not None and normal.next_tier.key == "honors"
    honors = evaluate(s, [section("a", 2, 2, 100, 95), section("opt", 1, 0, 10, 0)])
    assert honors.tier is not None and honors.tier.key == "honors"
    extra = evaluate(s, [section("a", 2, 2, 100, 95), section("opt", 1, 1, 10, 0)])
    assert extra.tier is not None and extra.tier.key == "extra"
    assert extra.next_tier is None


def test_optional_sections_do_not_lower_the_score() -> None:
    """Points of optional sections are left out; no points at all means 100 %."""
    s = settings(optional_section_ids=("opt",))
    result = evaluate(s, [section("a", 1, 1, 0, 0), section("opt", 1, 0, 50, 0)])
    assert result.score_pct == 100 and result.passed


def test_tier_validation() -> None:
    """Duplicate keys, missing labels and bad colours are refused."""
    label = {"en": "A", "ru": "А", "uz": "A"}
    with pytest.raises(CourseCertificateInvalidError):
        parse_tiers([{"key": "a", "label": label}, {"key": "a", "label": label}])
    with pytest.raises(CourseCertificateInvalidError):
        parse_tiers([{"key": "a", "label": {"en": "A"}}])
    with pytest.raises(CourseCertificateInvalidError):
        parse_tiers([{"key": "a", "label": label, "color": "red"}])
    with pytest.raises(CourseCertificateInvalidError):
        parse_fields([{**default_fields()[0], "font": "comic_sans"}])


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "#ffffff").save(out, "PNG")
    return out.getvalue()


def test_upload_accepts_png_and_strips_to_png() -> None:
    """A PNG is re-encoded; huge sides are scaled down."""
    data, width, height = course_render.normalize_image(_png(5000, 100))
    assert data.startswith(b"\x89PNG") and width == 4000 and height == 80


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"GIF89a" + b"\0" * 64, "type"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "type"),
        (b"%PDF-1.7\n1 0 obj << /Type /Catalog /Pages 9 0 R >>\n%%EOF", "corrupt"),
        (b"\x89PNG\r\n\x1a\n" + b"garbage" * 10, "corrupt"),
        (b"%PDF-" + b"A" * (11 * 1024 * 1024), "too_large"),
    ],
)
def test_upload_rejects_bad_files(payload: bytes, reason: str) -> None:
    """Other types, broken PDFs and PNGs and oversized files are refused."""
    with pytest.raises(CertificateUploadRejectedError) as caught:
        course_render.normalize_image(payload)
    assert caught.value.params == {"reason": reason}


def test_upload_rejects_a_pixel_bomb() -> None:
    """A small PNG declaring 10000 x 10000 pixels is refused before decoding."""
    with pytest.raises(CertificateUploadRejectedError) as caught:
        course_render.normalize_image(_png(10000, 5000))
    assert caught.value.params == {"reason": "too_many_pixels"}


def test_render_draws_text_and_qr_in_every_style() -> None:
    """Uzbek and Russian names render; the PDF is a PDF."""
    for style in ("square", "rounded", "dots"):
        template = {
            "fields": default_fields(),
            "qr": {**parse_qr(None), "style": style},
        }
        image = course_render.render(
            template,
            None,
            {"name": "Oʻgʻiloy Qahhorova", "course": "Физика"},
            "https://x",
        )
        assert image.size == course_render.BLANK_SIZE
    assert course_render.to_pdf(image).startswith(b"%PDF")
