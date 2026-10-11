"""Login names: ``surname.name`` in lowercase Latin (spec -> Models -> User)."""

from app.shared.text import slugify


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
