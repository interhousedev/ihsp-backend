"""File names inside the export archive: ``{GROUP}-{NAME}-{filename}``."""

import re
from pathlib import PurePosixPath

_BAD = re.compile(r'[\x00-\x1f\\/:*?"<>|]+')
_SPACES = re.compile(r"\s+")
MAX_PART = 120


def sanitize(part: str) -> str:
    """Make one part safe as a file name piece (no separators, no control chars)."""
    cleaned = _SPACES.sub(" ", _BAD.sub(" ", part)).strip(" .")
    return cleaned[:MAX_PART].strip(" .")


def archive_name(group: str, student: str, filename: str) -> str:
    """Return ``GROUP-NAME-filename`` with every part sanitized."""
    pieces = [sanitize(group), sanitize(student), sanitize(filename)]
    return "-".join(piece for piece in pieces if piece) or "file"


class NameDeduper:
    """Adds " (2)", " (3)" before the extension of names seen before."""

    def __init__(self) -> None:
        """Start with no names."""
        self._seen: set[str] = set()

    def unique(self, name: str) -> str:
        """Return the name, or a numbered variant when it was handed out already."""
        candidate = name
        path = PurePosixPath(name)
        number = 1
        while candidate.casefold() in self._seen:
            number += 1
            candidate = f"{path.stem} ({number}){path.suffix}"
        self._seen.add(candidate.casefold())
        return candidate
