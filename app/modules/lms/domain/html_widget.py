"""Custom HTML widgets: validation of an author upload and the signed file paths.

A widget is either one ``.html`` file (stored as ``index.html``) or a zip with
``index.html`` at its root plus scripts, styles, data, images, fonts and media.
The files are served unpacked from a signed path inside a sandboxed frame, so
only file types a browser renders passively or as part of that page are kept.
"""

import io
import zipfile
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.lms.domain.h5p_package import H5PPackageError, safe_path

WIDGET_MAX_UPLOAD_BYTES: Final = 20 * 1024 * 1024
WIDGET_MAX_UNPACKED_BYTES: Final = 60 * 1024 * 1024
WIDGET_MAX_FILES: Final = 500
WIDGET_ENTRY: Final = "index.html"
# The signed path is a bearer link not bound to the user: keep it short-lived.
WIDGET_TOKEN_SECONDS: Final = 600

CONTENT_TYPES: Final[dict[str, str]] = {
    "html": "text/html; charset=utf-8",
    "htm": "text/html; charset=utf-8",
    "js": "text/javascript; charset=utf-8",
    "mjs": "text/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "json": "application/json",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "avif": "image/avif",
    "svg": "image/svg+xml",
    "ico": "image/x-icon",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "ttf": "font/ttf",
    "otf": "font/otf",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "webm": "video/webm",
    "ogv": "video/ogg",
    "vtt": "text/vtt",
}

_LITTER: Final = (".DS_Store", "Thumbs.db")


class WidgetPackageError(ValueError):
    """The upload is not an acceptable widget; ``reason`` says why."""

    def __init__(self, reason: str, detail: str = "") -> None:
        """Store the machine-readable reason (``not-zip``, ``no-index``, ...)."""
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class WidgetEntry:
    """One file of a widget."""

    path: str
    data: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class WidgetPackage:
    """A validated widget: every file, ``index.html`` among them."""

    entries: tuple[WidgetEntry, ...]

    @property
    def byte_size(self) -> int:
        """Return the unpacked size."""
        return sum(len(entry.data) for entry in self.entries)


def widget_content_type(path: str) -> str | None:
    """Return the media type of an allowed file name, or None when not allowed."""
    base = path.rsplit("/", 1)[-1]
    if "." not in base:
        return None
    return CONTENT_TYPES.get(base.rpartition(".")[2].lower())


def widget_path(name: str) -> str:
    """Return the normalised relative path of a file of the widget.

    Raises:
        WidgetPackageError: Absolute, climbing out (``..``), a drive or odd bytes.
    """
    try:
        return safe_path(name)
    except H5PPackageError as exc:
        raise WidgetPackageError("unsafe-path", name) from exc


def parse_widget(
    data: bytes,
    filename: str,
    *,
    max_bytes: int = WIDGET_MAX_UPLOAD_BYTES,
    max_unpacked: int = WIDGET_MAX_UNPACKED_BYTES,
    max_files: int = WIDGET_MAX_FILES,
) -> WidgetPackage:
    """Validate an upload: a single ``.html`` file or a ``.zip`` with ``index.html``.

    Raises:
        WidgetPackageError: Too large, an unknown upload type, not a zip, no
            ``index.html`` at the root, a bad path, a file type that is not
            allowed, too many files or a duplicate path.
    """
    if len(data) > max_bytes:
        raise WidgetPackageError("too-large", str(max_bytes))
    kind = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if kind in ("html", "htm"):
        if len(data) > max_unpacked:
            raise WidgetPackageError("too-large", str(max_unpacked))
        return WidgetPackage((WidgetEntry(WIDGET_ENTRY, data, CONTENT_TYPES["html"]),))
    if kind != "zip":
        raise WidgetPackageError("file-type", filename[:200])
    entries = _unzip(data, max_unpacked, max_files)
    if not any(entry.path == WIDGET_ENTRY for entry in entries):
        raise WidgetPackageError("no-index")
    return WidgetPackage(tuple(entries))


def _unzip(data: bytes, max_unpacked: int, max_files: int) -> list[WidgetEntry]:
    """Open the zip and read its entries; a broken archive is ``not-zip``."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise WidgetPackageError("not-zip") from exc
    with archive:
        try:
            return _read_entries(archive, max_unpacked, max_files)
        except (zipfile.BadZipFile, NotImplementedError, EOFError) as exc:
            raise WidgetPackageError("not-zip", str(exc)) from exc


def _read_entries(
    archive: zipfile.ZipFile, max_unpacked: int, max_files: int
) -> list[WidgetEntry]:
    """Check every entry and read it, never more than ``max_unpacked`` in all."""
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > max_files:
        raise WidgetPackageError("too-many-files", str(max_files))
    if sum(info.file_size for info in infos) > max_unpacked:
        raise WidgetPackageError("too-large", str(max_unpacked))
    entries: list[WidgetEntry] = []
    seen: set[str] = set()
    budget = max_unpacked
    for info in infos:
        path = widget_path(info.filename)
        if path.startswith("__MACOSX/") or path.rsplit("/", 1)[-1] in _LITTER:
            continue
        content_type = widget_content_type(path)
        if content_type is None:
            raise WidgetPackageError("file-type", path)
        if path in seen:
            raise WidgetPackageError("duplicate-path", path)
        seen.add(path)
        with archive.open(info) as stream:
            body = stream.read(budget + 1)  # the header sizes may lie
        budget -= len(body)
        if budget < 0:
            raise WidgetPackageError("too-large", str(max_unpacked))
        entries.append(WidgetEntry(path, body, content_type))
    return entries


def widget_prefix(course_id: UUID, package_id: UUID) -> str:
    """Return the object key prefix of a stored widget (its own, not H5P's)."""
    return f"lms/courses/{course_id}/html-widgets/{package_id}/"
