"""The table of contents of a file as it is kept in the file's metadata (JSON)."""

from typing import Any

from app.shared.contracts.files import OutlineEntry

OUTLINE_KEY = "outline"
PAGES_KEY = "pages"


def outline_to_metadata(entries: tuple[OutlineEntry, ...]) -> list[dict[str, Any]]:
    """Return the JSON form of the entries."""
    return [
        {
            "title": entry.title,
            "page": entry.page,
            "href": entry.href,
            "level": entry.level,
        }
        for entry in entries
    ]


def outline_from_metadata(raw: object) -> list[OutlineEntry]:
    """Return the usable entries of stored metadata; anything else is skipped."""
    if not isinstance(raw, list):
        return []
    entries: list[OutlineEntry] = []
    for item in raw:
        entry = _entry(item)
        if entry is not None:
            entries.append(entry)
    return entries


def _entry(item: object) -> OutlineEntry | None:
    """One stored entry, or None when its fields have the wrong types."""
    if not isinstance(item, dict):
        return None
    title, page, href, level = (
        item.get("title"),
        item.get("page"),
        item.get("href"),
        item.get("level"),
    )
    if not isinstance(title, str) or not isinstance(level, int):
        return None
    if page is not None and not isinstance(page, int):
        return None
    if href is not None and not isinstance(href, str):
        return None
    return OutlineEntry(title=title, page=page, href=href, level=level)


def pages_from_metadata(metadata: dict[str, Any]) -> int | None:
    """Return the stored page (or chapter) count, if there is a sensible one."""
    pages = metadata.get(PAGES_KEY)
    return pages if isinstance(pages, int) and pages > 0 else None
