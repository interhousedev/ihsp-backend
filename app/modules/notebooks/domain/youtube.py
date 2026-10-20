"""YouTube links: the id of the video a URL points at (pure, no network)."""

import re
from collections.abc import Iterable
from urllib.parse import urlsplit

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"})
SHORT_HOST = "youtu.be"
# The path forms that carry the id as the segment after the prefix.
PATH_PREFIXES = ("/shorts/", "/embed/", "/live/", "/v/")


def youtube_video_id(url: str) -> str | None:
    """The 11-character id of a YouTube video URL, or None for any other URL.

    Recognised: ``youtube.com/watch?v=<id>``, ``youtu.be/<id>``, and the
    ``/shorts/``, ``/embed/``, ``/live/`` and ``/v/`` paths of youtube.com.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host == SHORT_HOST:
        return _valid(parts.path.lstrip("/").split("/", 1)[0])
    if host not in YOUTUBE_HOSTS:
        return None
    if parts.path == "/watch":
        values = _query_values(parts.query, "v")
        return _valid(values[0]) if values else None
    for prefix in PATH_PREFIXES:
        if parts.path.startswith(prefix):
            return _valid(parts.path[len(prefix) :].split("/", 1)[0])
    return None


def _query_values(query: str, key: str) -> list[str]:
    """The values of one query parameter, in order."""
    found: list[str] = []
    for pair in query.split("&"):
        name, _, value = pair.partition("=")
        if name == key:
            found.append(value)
    return found


def _valid(candidate: str) -> str | None:
    """The candidate when it has the shape of a video id."""
    return candidate if VIDEO_ID.fullmatch(candidate) else None


def render_transcript(lines: Iterable[tuple[float, str]]) -> str:
    """The transcript as text, one ``[m:ss] line`` per segment (``[h:mm:ss]`` if long).

    Blank segments are dropped and line breaks inside a segment become spaces, so the
    timestamps stay one per line for the chunker's paragraph split.
    """
    rendered: list[str] = []
    for start, text in lines:
        spoken = " ".join(text.split())
        if spoken:
            rendered.append(f"[{_clock(start)}] {spoken}")
    return "\n".join(rendered)


def _clock(seconds: float) -> str:
    """Seconds as ``m:ss``, or ``h:mm:ss`` from one hour on."""
    total = max(int(seconds), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
