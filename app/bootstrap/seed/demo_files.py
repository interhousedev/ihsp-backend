"""Demo files built in code at seed time: a PDF worksheet, a DOCX sheet, a PNG, a TXT.

Nothing binary is kept in the repository. Each builder returns a few KB at most and
the same bytes every time, so a second seed run stores nothing new.
"""

import io
import struct
import zlib
from collections.abc import Callable, Sequence

from docx import Document


def _pdf_text(value: str) -> str:
    """Escape a line for a PDF string; the base font only shows ASCII."""
    ascii_only = value.encode("ascii", "replace").decode("ascii")
    return ascii_only.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def worksheet_pdf(title: str, lines: Sequence[str]) -> bytes:
    """A one-page A4 worksheet: a bold title and the text lines under it."""
    text_lines = "".join(f"({_pdf_text(line)}) Tj T* " for line in lines)
    stream = (
        f"BT /F2 16 Tf 50 790 Td ({_pdf_text(title)}) Tj ET\n"
        f"BT /F1 11 Tf 16 TL 50 752 Td {text_lines}ET"
    ).encode("ascii")
    page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        page,
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        start,
    )
    return bytes(out)


def sheet_docx(title: str, paragraphs: Sequence[str]) -> bytes:
    """A Word homework sheet: a heading and one numbered paragraph per task."""
    document = Document()
    document.add_heading(title, level=1)
    for paragraph in paragraphs:
        document.add_paragraph(paragraph, style="List Number")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def notes_txt(lines: Sequence[str]) -> bytes:
    """Plain UTF-8 notes, one line each."""
    return ("\n".join(lines) + "\n").encode("utf-8")


class _Canvas:
    """A white RGB picture that can draw thick lines and outlined boxes."""

    WHITE = (255, 255, 255)

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(b"\xff" * (width * height * 3))

    def fill(
        self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]
    ) -> None:
        """Paint the rectangle [x0, x1) x [y0, y1), clipped to the picture."""
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(self.width, x1), min(self.height, y1)
        row = bytes(color) * max(0, x1 - x0)
        for y in range(y0, y1):
            start = (y * self.width + x0) * 3
            self.pixels[start : start + len(row)] = row

    def hline(
        self, x0: int, x1: int, y: int, thick: int, color: tuple[int, int, int]
    ) -> None:
        self.fill(min(x0, x1), y, max(x0, x1) + 1, y + thick, color)

    def vline(
        self, x: int, y0: int, y1: int, thick: int, color: tuple[int, int, int]
    ) -> None:
        self.fill(x, min(y0, y1), x + thick, max(y0, y1) + 1, color)

    def box(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        thick: int,
        color: tuple[int, int, int],
    ) -> None:
        """An outlined rectangle with a white inside (it hides lines behind it)."""
        self.fill(x0, y0, x1 + 1, y1 + 1, color)
        self.fill(x0 + thick, y0 + thick, x1 + 1 - thick, y1 + 1 - thick, self.WHITE)

    def png(self) -> bytes:
        """Encode the picture as an 8-bit RGB PNG."""
        rows = b"".join(
            b"\x00" + bytes(self.pixels[y * self.width * 3 : (y + 1) * self.width * 3])
            for y in range(self.height)
        )

        def chunk(kind: bytes, data: bytes) -> bytes:
            body = kind + data
            return (
                struct.pack(">I", len(data))
                + body
                + struct.pack(">I", zlib.crc32(body))
            )

        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows, 9))
            + chunk(b"IEND", b"")
        )


def circuit_png() -> bytes:
    """A 320 x 200 circuit diagram: a battery and a resistor on one closed loop."""
    dark = (31, 78, 121)
    canvas = _Canvas(320, 200)
    left, right, top, bottom, t = 40, 280, 40, 160, 3
    canvas.hline(left, right, top, t, dark)  # top wire
    canvas.hline(left, right, bottom, t, dark)  # bottom wire
    canvas.vline(right, top, bottom, t, dark)  # right wire
    canvas.vline(left, top, 88, t, dark)  # left wire, above the battery
    canvas.vline(left, 112, bottom, t, dark)  # left wire, below the battery
    canvas.hline(28, 52, 88, 4, dark)  # battery: long plate (+)
    canvas.hline(34, 46, 100, 6, dark)  # battery: short plate (-)
    canvas.box(150, 32, 190, 48, 2, dark)  # resistor R: its white inside hides the wire
    return canvas.png()


DEMO_FILES: dict[str, Callable[[], bytes]] = {
    "derivatives-worksheet.pdf": lambda: worksheet_pdf(
        "Worksheet: derivatives",
        [
            "1. d/dx (x^3 - 4x) = ?",
            "2. d/dx (x^2 * sin x) = ?  (product rule)",
            "3. d/dx ((2x + 1) / (x - 3)) = ?  (quotient rule)",
            "4. d/dx sqrt(5x - 2) = ?  (chain rule)",
            "5. Find the tangent line to y = x^2 at x = 2.",
            "Hand in the solutions on the next lesson.",
        ],
    ),
    "ohm-circuit.png": circuit_png,
    "unit6-notes.txt": lambda: notes_txt(
        [
            "Unit 6 notes: Learning and education",
            "",
            "Key words: curriculum, scholarship, graduate, tuition, deadline.",
            "Useful phrases: 'I'm planning to...', 'It depends on...'.",
            "Oqish: 'bilim - boylik' (knowledge is wealth).",
        ]
    ),
    "history-plan.docx": lambda: sheet_docx(
        "Tarix: Amir Temur davlati (reja)",
        [
            "Davlatning tashkil topishi (1370).",
            "Harbiy yurishlar va ularning natijalari.",
            "Poytaxt Samarqand va me'morchilik.",
            "Davlat boshqaruvi va qonunlar (Temur tuzuklari).",
            "Ilmiy hayot: Ulug'bek madrasasi.",
        ],
    ),
    "reaction-types.docx": lambda: sheet_docx(
        "Химические реакции: типы",
        [
            "Реакции соединения: A + B = AB.",
            "Реакции разложения: AB = A + B.",
            "Реакции замещения: A + BC = AC + B.",
            "Реакции обмена: AB + CD = AD + CB.",
        ],
    ),
}
