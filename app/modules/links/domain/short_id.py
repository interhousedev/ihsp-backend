"""Short IDs: generation and validation (SL-2, SL-3)."""

import random
from uuid import UUID

from app.modules.links.domain.link import LinkKind
from app.shared.ids import SHORT_ID_ALPHABET, SHORT_ID_PREFERRED

RESERVED = frozenset(
    {
        "ai",
        "api",
        "admin",
        "static",
        "r",
        "s",
        "robots.txt",
        "favicon.ico",
        "health",
        "ready",
        "v1",
        "mcp",
        "ical",
        "telegram",
    }
)
SHARE_PREFIXES = ("c-", "f-")
URL_LENGTH = 3
FILE_LENGTH = 8
GROW_AFTER_FAILURES = 5
MAX_ADMIN_LENGTH = 8
PREFERRED_RATIO = 0.7
_ALPHABET = frozenset(SHORT_ID_ALPHABET)


def generate(
    length: int, rng: random.Random, preferred_ratio: float = PREFERRED_RATIO
) -> str:
    """Return a random ID; each character is a digit or symbol with the given odds."""
    chars = []
    for _ in range(length):
        pool = (
            SHORT_ID_PREFERRED if rng.random() < preferred_ratio else SHORT_ID_ALPHABET
        )
        chars.append(rng.choice(pool))
    return "".join(chars)


def is_valid(slug: str) -> bool:
    """Check that a short ID uses only the alphabet and is not reserved."""
    if not slug or slug in RESERVED:
        return False
    if slug.startswith(SHARE_PREFIXES):
        return False
    return all(ch in _ALPHABET for ch in slug)


def is_lookup_slug(slug: str) -> bool:
    """Cheap check before a database lookup of a short link slug."""
    return (
        0 < len(slug) <= 64
        and slug not in RESERVED
        and all(ch in _ALPHABET for ch in slug)
    )


def base_length(
    kind: LinkKind, *, requested_length: int | None = None, is_admin: bool = False
) -> int:
    """Length of the first attempt: 3 for URLs, 8 for files, admins may pick 1-8."""
    if kind is LinkKind.FILE:
        return FILE_LENGTH
    if requested_length is not None and is_admin:
        return max(1, min(requested_length, MAX_ADMIN_LENGTH))
    return URL_LENGTH


def new_slug(
    kind: LinkKind,
    rng: random.Random,
    *,
    failures: int = 0,
    requested_length: int | None = None,
    is_admin: bool = False,
) -> str:
    """Build a candidate slug; it grows by one character per 5 failures in a row."""
    if kind is LinkKind.CHAT:
        return f"c-{_uuid4(rng)}"
    if kind is LinkKind.FLASHCARD_SET:
        return f"f-{_uuid4(rng)}"
    if kind is LinkKind.ARTIFACT:
        return f"a-{_uuid4(rng)}"
    length = base_length(kind, requested_length=requested_length, is_admin=is_admin)
    return generate(length + failures // GROW_AFTER_FAILURES, rng)


def _uuid4(rng: random.Random) -> UUID:
    return UUID(int=rng.getrandbits(128), version=4)
