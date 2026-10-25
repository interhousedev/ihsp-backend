"""Text of PPTX (one page per slide) and XLSX (shared strings and inline cells).

The XML parts are scanned for their text runs with a regular expression: no entity
expansion, and the zip is checked for bombs first, like DOCX.
"""

import html
import io
import re
import zipfile

from app.modules.files.domain.errors import TextExtractionError
from app.modules.files.infrastructure.extraction.limits import (
    MAX_TEXT_CHARS,
    MAX_ZIP_ENTRIES,
    MAX_ZIP_UNCOMPRESSED,
)
from app.modules.files.ports.text_extractor import ExtractedText

_SLIDE = re.compile(r"ppt/slides/slide(\d+)\.xml")
_SHEET = re.compile(r"xl/worksheets/sheet(\d+)\.xml")
_PARAGRAPH = re.compile(r"<a:p[ >].*?</a:p>", re.DOTALL)
_RUN = re.compile(r"<a:t(?:\s[^>]*)?>(.*?)</a:t>", re.DOTALL)
_CELL_TEXT = re.compile(r"<t(?:\s[^>]*)?>(.*?)</t>", re.DOTALL)
_ROW = re.compile(r"<row[ >].*?</row>", re.DOTALL)
_CELL = re.compile(r"<c\s([^>]*)>(.*?)</c>", re.DOTALL)
_VALUE = re.compile(r"<v>(.*?)</v>", re.DOTALL)


def _open(data: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise TextExtractionError("not a zip file") from exc
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise TextExtractionError("too many parts")
    if sum(info.file_size for info in infos) > MAX_ZIP_UNCOMPRESSED:
        raise TextExtractionError("too large when unpacked")
    return archive


def _numbered(archive: zipfile.ZipFile, pattern: re.Pattern[str]) -> list[str]:
    found = [
        (int(m.group(1)), n) for n in archive.namelist() if (m := pattern.fullmatch(n))
    ]
    return [name for _, name in sorted(found)]


def _read(archive: zipfile.ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8", errors="replace")


def _join(parts: list[str]) -> ExtractedText:
    starts: list[int] = []
    length = 0
    kept: list[str] = []
    for part in parts:
        offset = length + (1 if kept else 0)
        if offset >= MAX_TEXT_CHARS:
            break
        text = part[: MAX_TEXT_CHARS - offset]
        kept.append(text)
        starts.append(offset)
        length = offset + len(text)
    return ExtractedText(
        text="\n".join(kept), pages=len(kept) or None, page_starts=tuple(starts)
    )


def extract_pptx(data: bytes) -> ExtractedText:
    """One page per slide; each paragraph of a slide on its own line."""
    with _open(data) as archive:
        slides = []
        for name in _numbered(archive, _SLIDE):
            xml = _read(archive, name)
            lines = [
                "".join(html.unescape(run) for run in _RUN.findall(paragraph)).strip()
                for paragraph in _PARAGRAPH.findall(xml)
            ]
            slides.append("\n".join(line for line in lines if line))
    return _join(slides)


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    xml = _read(archive, "xl/sharedStrings.xml")
    return [
        "".join(html.unescape(t) for t in _CELL_TEXT.findall(item))
        for item in re.findall(r"<si>(.*?)</si>", xml, re.DOTALL)
    ]


def _cell_value(attributes: str, body: str, strings: list[str]) -> str:
    value = _VALUE.search(body)
    if 't="s"' in attributes and value is not None:
        index = int(value.group(1)) if value.group(1).isdigit() else -1
        return strings[index] if 0 <= index < len(strings) else ""
    if 't="inlineStr"' in attributes:
        return "".join(html.unescape(t) for t in _CELL_TEXT.findall(body))
    return html.unescape(value.group(1)) if value is not None else ""


def extract_xlsx(data: bytes) -> ExtractedText:
    """One page per sheet; a row per line, cells separated by ` | `."""
    with _open(data) as archive:
        strings = _shared_strings(archive)
        sheets = []
        for name in _numbered(archive, _SHEET):
            rows = []
            for row in _ROW.findall(_read(archive, name)):
                cells = [
                    _cell_value(attributes, body, strings).strip()
                    for attributes, body in _CELL.findall(row)
                ]
                if any(cells):
                    rows.append(" | ".join(cells))
            sheets.append("\n".join(rows))
    return _join(sheets)
