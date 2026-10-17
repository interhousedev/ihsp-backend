"""Login names: ``surname.name`` in lowercase Latin (spec -> Models -> User)."""

import re

from app.modules.identity.domain.errors import InvalidLoginError
from app.shared.text import slugify

LOGIN_MIN_LENGTH = 3
LOGIN_MAX_LENGTH = 100
# Lowercase Latin letters and digits, dot-separated: what base_login produces.
_LOGIN_RE = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*")


def check_login(value: str) -> str:
    """Return the login trimmed and lowercased, or raise InvalidLoginError."""
    clean = value.strip().lower()
    if not LOGIN_MIN_LENGTH <= len(clean) <= LOGIN_MAX_LENGTH:
        raise InvalidLoginError()
    if _LOGIN_RE.fullmatch(clean) is None:
        raise InvalidLoginError()
    return clean


def base_login(last_name: str, first_name: str) -> str:
    """Return ``surname.name`` for a person, e.g. ``brastilov.aleksey``."""
    surname = slugify(last_name).replace("-", "")
    name = slugify(first_name).replace("-", "")
    return f"{surname}.{name}"


def next_free(base: str, taken: set[str]) -> str:
    """Return ``base``, or ``base2``, ``base3``, ... when the name is taken."""
    if base not in taken:
        return base
    number = 2
    while f"{base}{number}" in taken:
        number += 1
    return f"{base}{number}"
