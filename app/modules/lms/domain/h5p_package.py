"""H5P packages: validation of an uploaded ``.h5p`` file (a zip) and its file list.

An H5P package holds ``h5p.json`` (title, main library, dependencies), the content
in ``content/`` and the libraries in ``<Library-1.2>/`` folders. The player
(h5p-standalone in the browser) reads them by relative path, so the package is
stored unpacked, one object per entry.
"""

import io
import json
import posixpath
import zipfile
from dataclasses import dataclass
from typing import Final

H5P_MAX_PACKAGE_BYTES: Final = 100 * 1024 * 1024
H5P_MAX_UNPACKED_BYTES: Final = 300 * 1024 * 1024
H5P_MAX_FILES: Final = 5000

CONTENT_TYPES: Final[dict[str, str]] = {
    "json": "application/json",
    "js": "text/javascript",
    "css": "text/css",
    "txt": "text/plain",
    "md": "text/plain",
    "csv": "text/csv",
    "xml": "application/xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "svg": "image/svg+xml",
    "webp": "image/webp",
    "ico": "image/x-icon",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "weba": "audio/webm",
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "webm": "video/webm",
    "ogv": "video/ogg",
    "vtt": "text/vtt",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "ttf": "font/ttf",
    "otf": "font/otf",
    "eot": "application/vnd.ms-fontobject",
    "pdf": "application/pdf",
}


class H5PPackageError(ValueError):
    """The upload is not an acceptable H5P package; ``reason`` says why."""

    def __init__(self, reason: str, detail: str = "") -> None:
        """Store the machine-readable reason (``not-zip``, ``no-h5p-json``, ...)."""
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class H5PEntry:
    """One file of an unpacked package."""

    path: str
    data: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class H5PPackage:
    """A validated package: metadata of ``h5p.json`` and every file."""

    title: str
    main_library: str
    entries: tuple[H5PEntry, ...]

    @property
    def byte_size(self) -> int:
        """Return the unpacked size."""
        return sum(len(entry.data) for entry in self.entries)


def content_type_of(path: str) -> str | None:
    """Return the media type of an allowed file name, or None when not allowed."""
    _, _, extension = path.rpartition(".")
    if "." not in path:
        return None
    return CONTENT_TYPES.get(extension.lower())


def safe_path(name: str) -> str:
    """Return the normalised relative path of a zip entry.

    Raises:
        H5PPackageError: The name is absolute, climbs out (``..``) or is odd.
    """
    if "\\" in name or "\x00" in name or name.startswith("/"):
        raise H5PPackageError("unsafe-path", name)
    normal = posixpath.normpath(name)
    parts = normal.split("/")
    if normal in ("", ".") or ".." in parts or (parts[0].endswith(":")):
        raise H5PPackageError("unsafe-path", name)
    return normal


def parse_package(
    data: bytes,
    *,
    max_bytes: int = H5P_MAX_PACKAGE_BYTES,
    max_unpacked: int = H5P_MAX_UNPACKED_BYTES,
) -> H5PPackage:
    """Validate an ``.h5p`` upload and return its files.

    Directories and files of other types are rejected rather than skipped, except
    the usual archive litter (``__MACOSX/``, ``.DS_Store``, ``Thumbs.db``).

    Raises:
        H5PPackageError: Too large, not a zip, no ``h5p.json``, a bad path, a file
            type that is not allowed, or an invalid ``h5p.json``.
    """
    if len(data) > max_bytes:
        raise H5PPackageError("too-large", str(max_bytes))
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise H5PPackageError("not-zip") from exc
    with archive:
        try:
            entries = _read_entries(archive, max_unpacked)
        except (zipfile.BadZipFile, NotImplementedError, EOFError) as exc:
            raise H5PPackageError("not-zip", str(exc)) from exc
    manifest = next((e for e in entries if e.path == "h5p.json"), None)
    if manifest is None:
        raise H5PPackageError("no-h5p-json")
    if not any(e.path == "content/content.json" for e in entries):
        raise H5PPackageError("no-content-json")
    title, main = _read_manifest(manifest.data)
    return H5PPackage(title=title, main_library=main, entries=tuple(entries))


def _read_entries(archive: zipfile.ZipFile, max_unpacked: int) -> list[H5PEntry]:
    """Check every entry and read it, never more than ``max_unpacked`` in all."""
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > H5P_MAX_FILES:
        raise H5PPackageError("too-many-files", str(H5P_MAX_FILES))
    if sum(info.file_size for info in infos) > max_unpacked:
        raise H5PPackageError("too-large", str(max_unpacked))
    entries: list[H5PEntry] = []
    seen: set[str] = set()
    budget = max_unpacked
    for info in infos:
        path = safe_path(info.filename)
        base = path.rsplit("/", 1)[-1]
        if path.startswith("__MACOSX/") or base in (".DS_Store", "Thumbs.db"):
            continue
        content_type = content_type_of(path)
        if content_type is None:
            raise H5PPackageError("file-type", path)
        if path in seen:
            raise H5PPackageError("duplicate-path", path)
        seen.add(path)
        with archive.open(info) as stream:
            body = stream.read(budget + 1)  # the header sizes may lie
        budget -= len(body)
        if budget < 0:
            raise H5PPackageError("too-large", str(max_unpacked))
        entries.append(H5PEntry(path, body, content_type))
    return entries


def _read_manifest(data: bytes) -> tuple[str, str]:
    """Return the title and main library of ``h5p.json``."""
    try:
        meta = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise H5PPackageError("bad-h5p-json") from exc
    if not isinstance(meta, dict):
        raise H5PPackageError("bad-h5p-json")
    main = meta.get("mainLibrary")
    if not isinstance(main, str) or not main:
        raise H5PPackageError("bad-h5p-json", "mainLibrary")
    title = meta.get("title")
    return (title if isinstance(title, str) else "")[:500], main[:200]
