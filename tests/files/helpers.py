"""Helpers of the files tests: tiny real PDFs, DOCX files and upload steps."""

import base64
import hashlib
import io
import struct
import zlib
from uuid import UUID

from app.modules.files.application.file_views import FileView
from app.modules.files.application.request_upload import UploadTicket
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose
from tests.fakes.files.services import FilesFakes

from docx import Document

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
EXE_BYTES = b"MZ" + b"\x90" * 64
PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def sha256_b64(data: bytes) -> str:
    """Base64 of the raw SHA-256 digest, as the browser sends it."""
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def make_pdf(*pages: str) -> bytes:
    """Build a valid PDF whose pages contain the given texts (Helvetica)."""
    objects: list[bytes] = []
    page_ids = [3 + 2 * i for i in range(len(pages))]
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    font_id = 3 + 2 * len(pages)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    for index, text in enumerate(pages):
        content_id = page_ids[index] + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode()
        )
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 20 150 Td ({escaped}) Tj ET".encode()
        objects.append(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def make_docx(*paragraphs: str, table: list[list[str]] | None = None) -> bytes:
    """Build a DOCX with paragraphs and an optional table."""
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if table:
        grid = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                grid.cell(r, c).text = value
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


async def upload_and_complete(
    fakes: FilesFakes,
    actor: Actor,
    *,
    name: str,
    data: bytes,
    content_type: str,
    purpose: FilePurpose = FilePurpose.LINK,
) -> FileView:
    """Run request_upload, the browser's PUT and complete_upload."""
    services = fakes.services
    ticket: UploadTicket = await services.request_upload.execute(
        actor,
        name=name,
        size=len(data),
        content_type=content_type,
        sha256_b64=sha256_b64(data),
        purpose=purpose,
    )
    fakes.storage.upload(ticket.upload, data)
    return await services.complete_upload.execute(actor, ticket.view.file.id)


async def upload_ready(
    fakes: FilesFakes,
    actor: Actor,
    *,
    name: str,
    data: bytes,
    content_type: str,
    purpose: FilePurpose = FilePurpose.LINK,
) -> UUID:
    """Upload, complete and process a file; return its id."""
    view = await upload_and_complete(
        fakes, actor, name=name, data=data, content_type=content_type, purpose=purpose
    )
    await fakes.services.process_file.execute(view.file.id)
    return view.file.id


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def real_png() -> bytes:
    """A valid 1x1 PNG (for the real libmagic)."""
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", pixels)
        + _png_chunk(b"IEND", b"")
    )


def real_jpeg() -> bytes:
    """The start of a JFIF JPEG (enough for the real libmagic)."""
    jfif = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    return b"\xff\xd8" + jfif + b"\xff\xd9"
