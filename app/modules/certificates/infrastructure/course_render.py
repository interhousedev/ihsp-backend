"""Upload checks and drawing of course certificates (Pillow, segno, pypdfium2)."""

import io
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from app.modules.certificates.domain.course.rules import FONTS
from app.modules.certificates.domain.errors import CertificateUploadRejectedError

import segno
from PIL import Image, ImageDraw, ImageFont

MAX_UPLOAD_BYTES: Final = 10 * 1024 * 1024
MAX_PIXELS: Final = 40_000_000
MAX_SIDE: Final = 4000
BLANK_SIZE: Final = (3508, 2480)  # A4 landscape at 300 dpi
FONT_DIR: Final = Path(__file__).parent / "fonts"


def _reject(reason: str) -> CertificateUploadRejectedError:
    return CertificateUploadRejectedError(params={"reason": reason})


def sniff(data: bytes) -> str:
    """Return ``png``, ``jpeg`` or ``pdf`` by magic bytes, or reject the file."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise _reject("too_large")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"%PDF-"):
        return "pdf"
    raise _reject("type")


def normalize_image(data: bytes, *, max_side: int = MAX_SIDE) -> tuple[bytes, int, int]:
    """Check an upload and re-encode it as a metadata-free PNG.

    PDFs give their first page. Images over 40 Mpx are refused before decoding;
    larger sides are scaled down to ``max_side``.
    """
    kind = sniff(data)
    try:
        image = _pdf_page(data) if kind == "pdf" else _raster(data)
    except CertificateUploadRejectedError:
        raise
    except Exception:  # noqa: BLE001 — any decoder failure is a bad upload
        raise _reject("corrupt") from None
    image.thumbnail((max_side, max_side))
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue(), image.width, image.height


def _raster(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as probe:
        if probe.format not in ("PNG", "JPEG"):
            raise _reject("type")
        if probe.width * probe.height > MAX_PIXELS:
            raise _reject("too_many_pixels")
        probe.load()
        return probe.copy()


def _pdf_page(data: bytes) -> Image.Image:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        if len(pdf) < 1:
            raise _reject("corrupt")
        page = pdf[0]
        width, height = page.get_size()
        if width <= 0 or height <= 0:
            raise _reject("corrupt")
        scale = min(MAX_SIDE / max(width, height), 300 / 72)
        rendered: Image.Image = page.render(scale=scale).to_pil().convert("RGB")
        return rendered
    finally:
        pdf.close()


@lru_cache(maxsize=64)
def _font(name: str, px: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_DIR / FONTS.get(name, FONTS["montserrat"])), px)
    try:
        axes = font.get_variation_axes()
        if axes:
            low, high = int(axes[0]["minimum"] or 0), int(axes[0]["maximum"] or 900)
            font.set_variation_by_axes([max(low, min(high, weight))])
    except OSError:
        pass
    return font


def font_path(name: str) -> Path | None:
    """Return the file of a bundled font (None for an unknown key)."""
    file = FONTS.get(name)
    return FONT_DIR / file if file else None


def qr_svg(url: str, fg: str = "#000000", bg: str = "#ffffff") -> str:
    """Return the QR code of a URL as SVG."""
    out = io.BytesIO()
    segno.make(url, error="m").save(out, kind="svg", scale=8, dark=fg, light=bg)
    return out.getvalue().decode()


def _draw_modules(
    draw: ImageDraw.ImageDraw,
    matrix: Any,
    origin: tuple[int, int],
    cell: float,
    style: dict[str, Any],
) -> None:
    left, top = origin
    for row, line in enumerate(matrix):
        for col, dark in enumerate(line):
            if not dark:
                continue
            x0, y0 = left + (col + 1) * cell, top + (row + 1) * cell
            rect = (x0, y0, x0 + cell, y0 + cell)
            if style["style"] == "dots":
                draw.ellipse(rect, fill=style["fg"])
            elif style["style"] == "rounded":
                draw.rounded_rectangle(rect, radius=cell * 0.35, fill=style["fg"])
            else:
                draw.rectangle(rect, fill=style["fg"])


def _draw_qr(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    url: str,
    style: dict[str, Any],
    logo: bytes | None,
) -> None:
    x, y, w, h = box
    side = max(21, min(w, h))
    left, top = x + (w - side) // 2, y + (h - side) // 2
    use_logo = bool(style.get("logo")) and logo is not None
    matrix = segno.make(url, error="h" if use_logo else "m").matrix
    count = len(matrix) + 2
    cell = side / count
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((left, top, left + side, top + side), fill=style["bg"])
    _draw_modules(draw, matrix, (left, top), cell, style)
    if use_logo and logo is not None:
        try:
            mark = Image.open(io.BytesIO(logo)).convert("RGBA")
        except Exception:  # noqa: BLE001 — a broken logo never breaks the certificate
            return
        size = int(side * 0.22)
        mark.thumbnail((size, size))
        cx, cy = left + side // 2, top + side // 2
        pad = max(2, size // 10)
        draw.rectangle(
            (cx - mark.width // 2 - pad, cy - mark.height // 2 - pad,
             cx + mark.width // 2 + pad, cy + mark.height // 2 + pad),
            fill=style["bg"],
        )  # fmt: skip
        canvas.alpha_composite(mark, (cx - mark.width // 2, cy - mark.height // 2))


def render(
    template: dict[str, Any],
    background: bytes | None,
    values: dict[str, str],
    qr_url: str,
    logo: bytes | None = None,
) -> Image.Image:
    """Draw a certificate: background, the placed text fields and the QR code."""
    if background:
        canvas = Image.open(io.BytesIO(background)).convert("RGBA")
    else:
        canvas = Image.new("RGBA", BLANK_SIZE, "#ffffff")
    width, height = canvas.size
    draw = ImageDraw.Draw(canvas)
    for spec in template.get("fields", []):
        box = (
            int(spec["x"] * width),
            int(spec["y"] * height),
            max(1, int(spec["w"] * width)),
            max(1, int(spec["h"] * height)),
        )
        if spec["key"] == "qr":
            _draw_qr(canvas, box, qr_url, template.get("qr") or {}, logo)
            draw = ImageDraw.Draw(canvas)
            continue
        text = (
            spec.get("text")
            if spec["key"] == "custom_text"
            else values.get(spec["key"])
        )
        if not text:
            continue
        px = max(6, int(spec["size"] * height))
        font = _font(spec["font"], px, int(spec.get("weight", 400)))
        while px > 6 and draw.textlength(text, font=font) > box[2]:
            px = int(px * 0.92)
            font = _font(spec["font"], px, int(spec.get("weight", 400)))
        align = spec.get("align", "center")
        anchor = {"left": "lm", "right": "rm"}.get(align, "mm")
        ax = {"left": box[0], "right": box[0] + box[2]}.get(align, box[0] + box[2] // 2)
        draw.text((ax, box[1] + box[3] // 2), text, font=font, fill=spec["color"],
                  anchor=anchor)  # fmt: skip
    return canvas


def to_png(image: Image.Image, max_side: int = 1600) -> bytes:
    """Return a preview PNG."""
    copy = image.copy()
    copy.thumbnail((max_side, max_side))
    out = io.BytesIO()
    copy.save(out, "PNG")
    return out.getvalue()


def to_pdf(image: Image.Image) -> bytes:
    """Return a one-page PDF at 300 dpi."""
    out = io.BytesIO()
    image.convert("RGB").save(out, "PDF", resolution=300.0)
    return out.getvalue()
