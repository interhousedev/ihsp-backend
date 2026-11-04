"""File names and photo format of the group photo export (ADM-PHOTO-2)."""

import re
import unicodedata

MAX_STEM_CHARS = 100
_RESERVED = re.compile(r'[\\/:*?"<>|]')
_DOTS = re.compile(r"\.{2,}")
_SPACES = re.compile(r"\s+")
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def full_name(last_name: str, first_name: str, middle_name: str | None) -> str:
    """The student's name as the registry writes it: last, first, middle."""
    parts = [last_name, first_name, middle_name or ""]
    return " ".join(part.strip() for part in parts if part.strip())


def safe_stem(name: str, fallback: str = "student") -> str:
    """A file name without the parts a zip or a file system must not get.

    Path separators, reserved characters, control characters and ``..`` are removed,
    letters of any alphabet (Cyrillic, Uzbek) are kept, and the result is at most
    ``MAX_STEM_CHARS`` long.
    """
    text = unicodedata.normalize("NFC", name)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    text = _RESERVED.sub(" ", text)
    text = _DOTS.sub(" ", text)
    text = _SPACES.sub(" ", text).strip(" .")
    text = text[:MAX_STEM_CHARS].rstrip(" .")
    return text or fallback


class EntryNames:
    """Hands out unique archive names: ``Name (2).jpg`` for the second copy.

    Uniqueness is case-insensitive, because Windows and macOS file systems are.
    """

    def __init__(self) -> None:
        """Start with no names taken."""
        self._taken: set[str] = set()

    def claim(self, name: str) -> str:
        """Reserve the name, or the first free numbered variant of it."""
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        candidate = name
        number = 2
        while candidate.casefold() in self._taken:
            candidate = f"{stem} ({number})" + (f".{ext}" if ext else "")
            number += 1
        self._taken.add(candidate.casefold())
        return candidate


def unique_entry_names(names: list[str]) -> list[str]:
    """The names with duplicates numbered, in order."""
    claims = EntryNames()
    return [claims.claim(name) for name in names]


def detect_photo_extension(data: bytes) -> str | None:
    """``jpg`` or ``png`` by the first bytes; None for anything else."""
    if data.startswith(_JPEG_MAGIC):
        return "jpg"
    if data.startswith(_PNG_MAGIC):
        return "png"
    return None
