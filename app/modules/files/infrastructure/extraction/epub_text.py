"""Text of EPUB books (a zip of XHTML files): every spine chapter is one page.

The reading order is the package's spine. The contents come from the EPUB 3
navigation document or, for older books, from the NCX; they become the outline.
Only the package, the contents and the chapters are unpacked, never the images.
"""

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote
from xml.etree.ElementTree import Element, ParseError, fromstring

from app.modules.files.domain.errors import TextExtractionError
from app.modules.files.infrastructure.extraction.limits import (
    MAX_EPUB_CHAPTERS,
    MAX_EPUB_ENTRIES,
    MAX_OUTLINE_ENTRIES,
    MAX_OUTLINE_TITLE,
    MAX_TEXT_CHARS,
    MAX_ZIP_UNCOMPRESSED,
)
from app.modules.files.ports.text_extractor import ExtractedText
from app.shared.contracts.files import OutlineEntry

CONTAINER = "META-INF/container.xml"
NCX_TYPE = "application/x-dtbncx+xml"
_HTML_TYPES = frozenset({"application/xhtml+xml", "text/html"})
_SKIPPED = frozenset({"head", "script", "style", "title", "svg"})
_ROWS, _CELLS = "tr", frozenset({"td", "th"})
_BLOCKS = frozenset(
    {
        "p", "div", "section", "article", "aside", "header", "footer", "main",
        "blockquote", "pre", "figure", "figcaption", "ul", "ol", "li", "dl", "dt",
        "dd", "table", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "nav", "address",
    }
)  # fmt: skip
_MAX_DEPTH = 20
_SPACES = re.compile(r"\s+")
_Raw = tuple[str, str, int]  # (title, href as written, depth)


@dataclass(frozen=True, slots=True)
class _Item:
    """A manifest entry: ``href`` is relative to the package file, still %-encoded."""

    href: str
    media_type: str
    properties: frozenset[str]


@dataclass(frozen=True, slots=True)
class _Package:
    """The parts of the package file (OPF) that matter for reading."""

    folder: str  # folder of the package file inside the zip
    items: dict[str, _Item]
    spine: list[str]  # item ids in reading order
    toc_id: str | None


class _Archive:
    """The zip with a budget for the bytes unpacked (zip-bomb guard)."""

    def __init__(self, archive: zipfile.ZipFile) -> None:
        """Refuse archives with too many parts."""
        infos = archive.infolist()
        if len(infos) > MAX_EPUB_ENTRIES:
            raise TextExtractionError("epub has too many parts")
        self._archive = archive
        self._infos = {info.filename: info for info in infos}
        self._budget = MAX_ZIP_UNCOMPRESSED

    def read(self, name: str) -> bytes | None:
        """Return the part, or None when the archive has no such part."""
        info = self._infos.get(name)
        if info is None:
            return None
        if info.file_size > self._budget:
            raise TextExtractionError("epub text is too large when unpacked")
        self._budget -= info.file_size
        return self._archive.read(info)

    def require(self, name: str, what: str) -> bytes:
        """Return the part or fail: the book cannot be read without it."""
        data = self.read(name)
        if data is None:
            raise TextExtractionError(f"epub has no {what}")
        return data


# - - - Chapters (XHTML to text) - - -


class _TextParser(HTMLParser):
    """Turns a chapter into blocks: headings as ``#``, list items as ``- ``.

    Blocks are separated by blank lines, table rows are lines with tab-separated
    cells (the same reading as the DOCX extractor), scripts and styles are dropped.
    """

    def __init__(self) -> None:
        """Start with no text."""
        super().__init__(convert_charrefs=True)
        self._blocks: list[tuple[str, bool]] = []  # (text, is a table row)
        self._parts: list[str] = []
        self._prefix = ""
        self._skip = 0
        self._in_row = False
        self._cells = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open a block, a row or a cell; skip scripts."""
        if tag in _SKIPPED:
            self._skip += 1
        elif self._skip:
            return
        elif tag == "br":
            self._parts.append("\n")
        elif tag == _ROWS:
            self._flush(False)
            self._in_row, self._cells = True, 0
        elif tag in _CELLS and self._in_row:
            self._parts.append("\t" if self._cells else "")
            self._cells += 1
        elif tag in _BLOCKS and not self._in_row:
            self._flush(False)
            self._prefix = _prefix_of(tag) or self._prefix

    def handle_endtag(self, tag: str) -> None:
        """Close the block or the row."""
        if tag in _SKIPPED:
            self._skip = max(0, self._skip - 1)
        elif self._skip:
            return
        elif tag == _ROWS:
            self._flush(True)
            self._in_row = False
        elif tag in _BLOCKS and not self._in_row:
            self._flush(False)

    def handle_data(self, data: str) -> None:
        """Collect text; any run of white space is one space."""
        if not self._skip:
            self._parts.append(_SPACES.sub(" ", data))

    def _flush(self, row: bool) -> None:
        """End the current block (empty blocks vanish, a pending prefix stays)."""
        lines = "".join(self._parts).split("\n")
        self._parts = []
        text = "\n".join(line for line in map(_tidy, lines) if line)
        if not text:
            return
        self._blocks.append((self._prefix + text, row))
        self._prefix = ""

    def text(self) -> str:
        """Return all blocks; rows of one table stay together."""
        self._flush(False)
        out: list[str] = []
        previous_row = False
        for text, row in self._blocks:
            if out:
                out.append("\n" if row and previous_row else "\n\n")
            out.append(text)
            previous_row = row
        return "".join(out)


def _tidy(line: str) -> str:
    """Collapse runs of spaces and trim the line."""
    return re.sub(" {2,}", " ", line).strip(" ")


def _prefix_of(tag: str) -> str:
    """Markdown prefix of a heading or a list item."""
    if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
        return "#" * int(tag[1]) + " "
    return "- " if tag == "li" else ""


def _decode(data: bytes) -> str:
    """Decode a content document (UTF-8, or UTF-16 with a byte order mark)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def _chapter_text(data: bytes) -> str:
    """Plain text of one XHTML chapter."""
    parser = _TextParser()
    parser.feed(_decode(data))
    parser.close()
    return parser.text().replace("\x00", "")  # before the offsets are counted


# - - - Package - - -


def _local(tag: str) -> str:
    """Tag name without its namespace."""
    return tag.rpartition("}")[2]


def _rel(folder: str, href: str) -> str:
    """Normalise a path (no fragment or query) against a folder; '' when empty."""
    path = href.partition("#")[0].partition("?")[0]
    return posixpath.normpath(posixpath.join(folder, path)) if path else ""


def _read_package(archive: _Archive) -> _Package:
    """Find the package file through container.xml and read manifest and spine."""
    container = fromstring(archive.require(CONTAINER, "container.xml"))
    path = next(
        (e.get("full-path") for e in container.iterfind(".//{*}rootfile")), None
    )
    if not path:
        raise TextExtractionError("epub container names no package file")
    root = fromstring(archive.require(path, "package file"))
    items = {
        element.get("id", ""): _Item(
            href=_rel("", element.get("href", "")),
            media_type=element.get("media-type", ""),
            properties=frozenset(element.get("properties", "").split()),
        )
        for element in root.iterfind("{*}manifest/{*}item")
    }
    spine = [
        ref.get("idref", "")
        for ref in root.iterfind("{*}spine/{*}itemref")
        if ref.get("idref") in items
    ]
    if not spine:
        raise TextExtractionError("epub has no spine")
    toc = root.find("{*}spine")
    return _Package(
        folder=posixpath.dirname(path),
        items=items,
        spine=spine,
        toc_id=None if toc is None else toc.get("toc"),
    )


def _zip_path(package: _Package, rel: str) -> str:
    """Name of a part inside the zip."""
    return posixpath.join(package.folder, unquote(rel))


def _read_chapters(archive: _Archive, package: _Package) -> list[str]:
    """Texts of the chapters in reading order, until the text cap is reached."""
    texts: list[str] = []
    total = 0
    for item_id in package.spine[:MAX_EPUB_CHAPTERS]:
        item = package.items[item_id]
        data = (
            archive.read(_zip_path(package, item.href))
            if item.media_type in _HTML_TYPES
            else None
        )
        texts.append("" if data is None else _chapter_text(data))
        total += len(texts[-1])
        if total >= MAX_TEXT_CHARS:
            break
    return texts


# - - - Contents - - -


class _NavParser(HTMLParser):
    """Reads the ``<nav epub:type="toc">`` list of an EPUB 3 navigation document."""

    def __init__(self) -> None:
        """Start outside the contents."""
        super().__init__(convert_charrefs=True)
        self.entries: list[_Raw] = []
        self._in_toc = False
        self._depth = 0
        self._href: str | None = None
        self._title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track the nesting of lists and open a link."""
        values = dict(attrs)
        if tag == "nav":
            kinds = (values.get("epub:type") or "").split()
            self._in_toc = "toc" in kinds or values.get("role") == "doc-toc"
        elif self._in_toc and tag in {"ol", "ul"}:
            self._depth += 1
        elif self._in_toc and tag == "a" and values.get("href"):
            self._href, self._title = values["href"], []

    def handle_endtag(self, tag: str) -> None:
        """Close a link into an entry."""
        if tag == "nav":
            self._in_toc = False
        elif self._in_toc and tag in {"ol", "ul"}:
            self._depth = max(0, self._depth - 1)
        elif self._in_toc and tag == "a" and self._href is not None:
            self.entries.append(("".join(self._title), self._href, self._depth - 1))
            self._href = None

    def handle_data(self, data: str) -> None:
        """Collect the title of the open link."""
        if self._href is not None:
            self._title.append(data)


def _nav_entries(archive: _Archive, package: _Package) -> tuple[str, list[_Raw]]:
    """Entries of the EPUB 3 navigation document, with its folder."""
    for item in package.items.values():
        if "nav" in item.properties:
            data = archive.read(_zip_path(package, item.href))
            if data is not None:
                parser = _NavParser()
                parser.feed(_decode(data))
                return posixpath.dirname(item.href), parser.entries
    return "", []


def _ncx_points(parent: Element, depth: int, out: list[_Raw]) -> None:
    """Collect ``navPoint`` elements, children after their parent."""
    for point in parent.findall("{*}navPoint"):
        content = point.find("{*}content")
        src = "" if content is None else content.get("src", "")
        out.append((point.findtext("{*}navLabel/{*}text") or "", src, depth))
        if depth < _MAX_DEPTH and len(out) < MAX_OUTLINE_ENTRIES:
            _ncx_points(point, depth + 1, out)


def _ncx_entries(archive: _Archive, package: _Package) -> tuple[str, list[_Raw]]:
    """Entries of the EPUB 2 NCX, with its folder."""
    item = package.items.get(package.toc_id or "")
    if item is None:
        item = next(
            (i for i in package.items.values() if i.media_type == NCX_TYPE), None
        )
    data = None if item is None else archive.read(_zip_path(package, item.href))
    if item is None or data is None:
        return "", []
    entries: list[_Raw] = []
    try:
        nav_map = fromstring(data).find("{*}navMap")
    except ParseError:
        return "", []
    if nav_map is not None:
        _ncx_points(nav_map, 0, entries)
    return posixpath.dirname(item.href), entries


def _outline_entry(
    raw: _Raw, folder: str, pages: dict[str, int]
) -> OutlineEntry | None:
    """One outline entry: clean title, chapter number and href in the book."""
    title, href, depth = raw
    clean = _SPACES.sub(" ", title.replace("\x00", "")).strip()[:MAX_OUTLINE_TITLE]
    if not clean:
        return None
    path = _rel(folder, href)
    fragment = href.partition("#")[2]
    target = path + (f"#{fragment}" if fragment and path else "")
    return OutlineEntry(
        title=clean,
        page=pages.get(unquote(path)),
        href=target or None,
        level=max(0, depth),
    )


def _read_outline(archive: _Archive, package: _Package) -> tuple[OutlineEntry, ...]:
    """The contents of the book: navigation document first, then the NCX."""
    pages: dict[str, int] = {}
    for number, item_id in enumerate(package.spine, start=1):
        pages.setdefault(unquote(package.items[item_id].href), number)
    for read in (_nav_entries, _ncx_entries):
        folder, raws = read(archive, package)
        entries = [_outline_entry(raw, folder, pages) for raw in raws]
        found = [entry for entry in entries if entry is not None]
        if found:
            return tuple(found[:MAX_OUTLINE_ENTRIES])
    return ()


# - - - Entry point - - -


def extract_epub(data: bytes) -> ExtractedText:
    """Return the chapters as pages, the offsets where they start, and the contents.

    ``pages`` is the number of chapters. Offsets of chapters cut off by the text cap
    are dropped, as for PDFs.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zipped:
            archive = _Archive(zipped)
            package = _read_package(archive)
            chapters = _read_chapters(archive, package)
            outline = _read_outline(archive, package)
    except TextExtractionError:
        raise
    except Exception as exc:  # BadZipFile, ParseError, KeyError, zlib errors, ...
        raise TextExtractionError(f"epub: {exc}") from exc
    starts: list[int] = []
    position = 0
    for text in chapters:
        starts.append(position)
        position += len(text) + 1  # the newline that joins the chapters
    joined = "\n".join(chapters)
    if len(joined) > MAX_TEXT_CHARS:
        starts = [start for start in starts if start < MAX_TEXT_CHARS]
    return ExtractedText(
        text=joined[:MAX_TEXT_CHARS],
        pages=len(package.spine),
        page_starts=tuple(starts),
        outline=outline,
    )
