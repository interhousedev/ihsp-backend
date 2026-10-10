"""Cover images cut out of an uploaded book file (blocking: run in a thread).

PDF: the first page rendered as JPEG. EPUB: the cover image named in the OPF, else
the first image in the archive. Any failure gives None; a missing cover is not an
error.
"""

import io
import posixpath
import zipfile
from xml.etree import ElementTree

from app.modules.library.domain.enums import FileFormat

import pypdfium2

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp")
RENDER_SCALE = 1.5
MAX_COVER_BYTES = 5 * 1024 * 1024


def extract_cover(data: bytes, fmt: FileFormat) -> tuple[bytes, str] | None:
    """`(image bytes, file name)` of the cover, or None when there is none."""
    try:
        if fmt is FileFormat.PDF:
            return _pdf_cover(data)
        if fmt is FileFormat.EPUB:
            return _epub_cover(data)
    except Exception:  # noqa: BLE001  # any broken file simply has no cover
        return None
    return None


def _pdf_cover(data: bytes) -> tuple[bytes, str] | None:
    document = pypdfium2.PdfDocument(data)
    try:
        if len(document) == 0:
            return None
        image = document[0].render(scale=RENDER_SCALE).to_pil().convert("RGB")
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=85)
        return out.getvalue(), "cover.jpg"
    finally:
        document.close()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _opf_path(archive: zipfile.ZipFile) -> str | None:
    root = ElementTree.fromstring(archive.read("META-INF/container.xml"))
    for node in root.iter():
        if _local(node.tag) == "rootfile":
            return node.attrib.get("full-path")
    return None


def _opf_cover_href(archive: zipfile.ZipFile, opf: str) -> str | None:
    root = ElementTree.fromstring(archive.read(opf))
    items = {
        n.attrib.get("id"): n
        for n in root.iter()
        if _local(n.tag) == "item" and n.attrib.get("href")
    }
    for node in root.iter():
        if _local(node.tag) == "meta" and node.attrib.get("name") == "cover":
            item = items.get(node.attrib.get("content"))
            if item is not None:
                return item.attrib["href"]
    for item in items.values():
        if "cover-image" in item.attrib.get("properties", "").split():
            return item.attrib["href"]
    return None


def _epub_cover(data: bytes) -> tuple[bytes, str] | None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        chosen: str | None = None
        opf = _opf_path(archive)
        if opf:
            href = _opf_cover_href(archive, opf)
            if href:
                candidate = posixpath.normpath(
                    posixpath.join(posixpath.dirname(opf), href)
                )
                chosen = candidate if candidate in names else None
        if chosen is None:
            images = [n for n in names if n.lower().endswith(IMAGE_SUFFIXES)]
            chosen = images[0] if images else None
        if chosen is None:
            return None
        image = archive.read(chosen)
        if len(image) > MAX_COVER_BYTES:
            return None
        return image, posixpath.basename(chosen)
