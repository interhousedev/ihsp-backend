"""Reading a moderation search query: a slug, a share or short URL, or a login."""

from urllib.parse import unquote, urlsplit

_PATH_PREFIXES = ("s/", "ai/")


def extract_slug(query: str) -> str:
    """Return the slug in a full short or share URL; other input is returned as is."""
    text = query.strip()
    if "/" not in text:
        return text
    parts = urlsplit(text if "://" in text else f"//{text}")
    path = unquote(parts.path).lstrip("/")
    for prefix in _PATH_PREFIXES:
        if path.startswith(prefix):
            path = path[len(prefix) :]
    return path.split("/")[0]
