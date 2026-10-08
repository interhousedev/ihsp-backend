"""Text of DOCX files (python-docx: paragraphs and table rows, in order)."""

import io
import zipfile

from app.modules.files.domain.errors import TextExtractionError
from app.modules.files.infrastructure.extraction.limits import (
    MAX_TEXT_CHARS,
    MAX_ZIP_ENTRIES,
    MAX_ZIP_UNCOMPRESSED,
)
from app.modules.files.ports.text_extractor import ExtractedText

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


def _check_zip(data: bytes) -> None:
    """Refuse zip bombs before python-docx unpacks the parts."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise TextExtractionError("docx has too many parts")
    if sum(info.file_size for info in infos) > MAX_ZIP_UNCOMPRESSED:
        raise TextExtractionError("docx is too large when unpacked")


def _table_lines(table: Table) -> list[str]:
    return ["\t".join(cell.text for cell in row.cells) for row in table.rows]


def extract_docx(data: bytes) -> ExtractedText:
    """Return the paragraphs and tables of a document as plain text."""
    try:
        _check_zip(data)
        document = Document(io.BytesIO(data))
        lines: list[str] = []
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                lines.append(block.text)
            else:
                lines.extend(_table_lines(block))
    except TextExtractionError:
        raise
    except Exception as exc:  # BadZipFile, KeyError, lxml errors, ...
        raise TextExtractionError(f"docx: {exc}") from exc
    return ExtractedText(text="\n".join(lines)[:MAX_TEXT_CHARS])
