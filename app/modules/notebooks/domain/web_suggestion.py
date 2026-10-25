"""When a Studio output needs more sources than the notebook has, and its web query.

Nothing here searches the web: a suggestion only tells the web to offer a search,
which the student starts (searches cost quota).
"""

from collections.abc import Iterable
from typing import Final

QUERY_MAX_CHARS: Final = 200


def is_thin_sources(total_chars: int, source_count: int, threshold: int) -> bool:
    """True when there are no sources at all or their text is below the threshold."""
    return source_count == 0 or total_chars < threshold


def web_search_query(title: str | None, focus: str | None) -> str | None:
    """The web query from the title and focus text; None when both are empty."""
    words = " ".join(part for part in (title, focus) if part and part.strip())
    query = " ".join(words.split())[:QUERY_MAX_CHARS].strip()
    return query or None


def suggestion_for_request(
    *,
    char_counts: Iterable[int],
    title: str | None,
    focus: str | None,
    threshold: int,
) -> str | None:
    """The query to suggest when the sources of a request are thin; None otherwise."""
    counts = list(char_counts)
    if not is_thin_sources(sum(counts), len(counts), threshold):
        return None
    return web_search_query(title, focus)


def suggestion_for_content(
    content: dict[str, object] | None,
    *,
    verification_key: str,
    unverified: str,
    title: str | None,
    focus: str | None,
) -> str | None:
    """The query to suggest when the faithfulness check found unsupported text."""
    if not content:
        return None
    mark = content.get(verification_key)
    if not isinstance(mark, dict) or mark.get("status") != unverified:
        return None
    return web_search_query(title, focus)
