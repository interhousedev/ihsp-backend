"""Small validation rules for courses: slug, title, invite code."""

import re
import secrets
from typing import Final

from app.modules.lms.domain.authoring.errors import SlugInvalidError, TitleInvalidError
from app.shared.ids import SHORT_ID_ALPHABET

SLUG_PATTERN: Final = re.compile(r"[a-z0-9-]{3,60}")
TITLE_MAX_LENGTH: Final = 200
INVITE_CODE_LENGTH: Final = 10


def validate_slug(slug: str) -> str:
    """Return the slug if it matches `[a-z0-9-]{3,60}`."""
    if not SLUG_PATTERN.fullmatch(slug):
        raise SlugInvalidError(params={"slug": slug})
    return slug


def clean_title(title: str) -> str:
    """Trim a title and check that it has 1-200 characters."""
    value = title.strip()
    if not 1 <= len(value) <= TITLE_MAX_LENGTH:
        raise TitleInvalidError(params={"max_length": TITLE_MAX_LENGTH})
    return value


def new_invite_code() -> str:
    """Return a random 10-character invite code (about 58 bits)."""
    return "".join(secrets.choice(SHORT_ID_ALPHABET) for _ in range(INVITE_CODE_LENGTH))
