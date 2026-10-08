"""Split Telegram HTML into messages of at most 4096 characters.

Telegram counts characters after entity parsing, so tags do not count and an
entity such as ``&amp;`` counts as one. Tags left open at a cut are closed and
reopened in the next part.
"""

import re

MAX_MESSAGE_LENGTH = 4096

_TOKEN = re.compile(r"<[^>]*>|&#?\w+;|[^<&]+|[<&]")
_TAG_NAME = re.compile(r"</?\s*([a-zA-Z][\w-]*)")


def _units(text: str, limit: int) -> list[str]:
    """Cut the text into tokens: tags, entities and lines of at most ``limit``."""
    units: list[str] = []
    for token in _TOKEN.findall(text):
        if token.startswith("<") and token.endswith(">") or token.startswith("&"):
            units.append(token)
            continue
        for line in token.splitlines(keepends=True):
            units.extend(line[i : i + limit] for i in range(0, len(line), limit))
    return units


def _is_tag(unit: str) -> bool:
    return len(unit) > 1 and unit.startswith("<") and unit.endswith(">")


def _is_entity(unit: str) -> bool:
    return len(unit) > 1 and unit.startswith("&") and unit.endswith(";")


class _Splitter:
    """Accumulates units into parts while tracking the open tags."""

    def __init__(self, limit: int) -> None:
        """Start with an empty first part."""
        self.limit = limit
        self.parts: list[str] = []
        self.current: list[str] = []
        self.used = 0
        self.open_tags: list[tuple[str, str]] = []

    def feed(self, unit: str) -> None:
        """Add one unit, cutting before it when it does not fit."""
        if _is_tag(unit):
            self._tag(unit)
            return
        size = 1 if _is_entity(unit) else len(unit)
        if self.used + size > self.limit:
            self.cut()
        self.current.append(unit)
        self.used += size

    def _tag(self, unit: str) -> None:
        match = _TAG_NAME.match(unit)
        if match is None:
            self.current.append(unit)
            return
        name = match.group(1).lower()
        if unit.startswith("</"):
            if self.open_tags and self.open_tags[-1][0] == name:
                self.open_tags.pop()
        else:
            self.open_tags.append((name, unit))
        self.current.append(unit)

    def cut(self) -> None:
        """Close the open tags, store the part and reopen the tags."""
        if self.used == 0:
            return
        closing = "".join(f"</{name}>" for name, _ in reversed(self.open_tags))
        self.parts.append("".join(self.current) + closing)
        self.current = [tag for _, tag in self.open_tags]
        self.used = 0

    def finish(self) -> list[str]:
        """Return all parts (at least one)."""
        self.cut()
        return self.parts or [""]


def split_html(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split HTML text so that every part is at most ``limit`` visible characters."""
    splitter = _Splitter(limit)
    for unit in _units(text, limit):
        splitter.feed(unit)
    return splitter.finish()


def truncate_html(text: str, limit: int) -> tuple[str, bool]:
    """Return the first ``limit`` visible characters and whether anything was cut."""
    parts = split_html(text, limit)
    return parts[0], len(parts) > 1
