"""Reading a cartridge zip safely: size caps, zip-slip and zip-bomb protection.

Members are never written to disk; they are read into memory one at a time, so a
path like ``../../etc/passwd`` cannot escape anywhere. Such names are still
rejected because a cartridge that has them is broken or hostile.
"""

import io
import posixpath
import zipfile
from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote

from app.modules.lms.domain.cartridge.errors import CartridgeInvalidError

MAX_ARCHIVE_BYTES: Final = 200 * 1024 * 1024
MAX_MEMBERS: Final = 20_000
MAX_MEMBER_BYTES: Final = 100 * 1024 * 1024
MAX_TOTAL_BYTES: Final = 1024 * 1024 * 1024
MAX_RATIO: Final = 200  # uncompressed / compressed, for members over 1 MiB
RATIO_FLOOR_BYTES: Final = 1024 * 1024


@dataclass(frozen=True, slots=True)
class Limits:
    """Caps applied while opening an archive (tests use small ones)."""

    archive_bytes: int = MAX_ARCHIVE_BYTES
    members: int = MAX_MEMBERS
    member_bytes: int = MAX_MEMBER_BYTES
    total_bytes: int = MAX_TOTAL_BYTES
    ratio: int = MAX_RATIO


def normalize_member(name: str) -> str | None:
    """Return the clean POSIX path of a member, or None when it is unsafe.

    Unsafe: absolute paths, drive letters, ``..`` escaping the root, NUL bytes.
    Directory entries come back with their trailing slash removed.
    """
    if "\x00" in name:
        return None
    path = name.replace("\\", "/")
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        return None
    clean = posixpath.normpath(path)
    if clean in ("", ".") or clean == ".." or clean.startswith("../"):
        return None
    return clean


def resolve(base_dir: str, href: str) -> str | None:
    """Join a relative href to a directory inside the archive; None if it escapes."""
    target = unquote(href.split("#", 1)[0].split("?", 1)[0]).replace("\\", "/")
    if not target or target.startswith("/"):
        target = target.lstrip("/")
        base_dir = ""
    joined = posixpath.normpath(posixpath.join(base_dir, target)) if target else ""
    if joined in ("", ".") or joined == ".." or joined.startswith("../"):
        return None
    return joined


class CartridgeArchive:
    """The members of a cartridge zip, checked once and read on demand."""

    def __init__(self, data: bytes, limits: Limits | None = None) -> None:
        """Open and check the archive.

        Raises:
            CartridgeInvalidError: Not a zip, too large, too many members, an unsafe
                path, a member that inflates suspiciously, or no manifest.
        """
        self.limits = limits or Limits()
        if len(data) > self.limits.archive_bytes:
            raise CartridgeInvalidError(
                params={"reason": "too-large", "max_bytes": self.limits.archive_bytes}
            )
        try:
            self._zip = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, ValueError) as exc:
            raise CartridgeInvalidError(params={"reason": "not-zip"}) from exc
        self._members: dict[str, zipfile.ZipInfo] = {}
        self._lower: dict[str, str] = {}
        self._check()

    def _check(self) -> None:  # noqa: C901
        infos = self._zip.infolist()
        if len(infos) > self.limits.members:
            raise CartridgeInvalidError(
                params={"reason": "too-many-files", "max_files": self.limits.members}
            )
        total = 0
        for info in infos:
            clean = normalize_member(info.filename)
            if clean is None:
                raise CartridgeInvalidError(
                    params={"reason": "unsafe-path", "path": info.filename[:200]}
                )
            if info.is_dir():
                continue
            if info.file_size > self.limits.member_bytes:
                raise CartridgeInvalidError(
                    params={"reason": "too-large", "path": clean[:200]}
                )
            if info.file_size > RATIO_FLOOR_BYTES and info.file_size > (
                max(info.compress_size, 1) * self.limits.ratio
            ):
                raise CartridgeInvalidError(params={"reason": "bomb"})
            total += info.file_size
            if total > self.limits.total_bytes:
                raise CartridgeInvalidError(params={"reason": "bomb"})
            self._members[clean] = info
            self._lower.setdefault(clean.casefold(), clean)
        if "imsmanifest.xml" not in self._members:
            raise CartridgeInvalidError(params={"reason": "no-manifest"})

    @property
    def names(self) -> list[str]:
        """Every file in the archive (no directories), in archive order."""
        return list(self._members)

    def find(self, path: str | None) -> str | None:
        """Return the member name for a path, matched exactly or without case."""
        if not path:
            return None
        if path in self._members:
            return path
        return self._lower.get(path.casefold())

    def size(self, path: str) -> int:
        """Return the declared uncompressed size of a member."""
        return self._members[path].file_size

    def read(self, path: str) -> bytes:
        """Return a member's bytes, reading at most its declared size plus one byte.

        Raises:
            CartridgeInvalidError: The member inflates beyond its declared size.
        """
        info = self._members[path]
        with self._zip.open(info) as handle:
            data = handle.read(info.file_size + 1)
        if len(data) > info.file_size:
            raise CartridgeInvalidError(params={"reason": "bomb"})
        return data

    def read_text(self, path: str) -> str:
        """Return a member decoded as UTF-8 (BOM and bad bytes tolerated)."""
        return self.read(path).decode("utf-8-sig", errors="replace")
