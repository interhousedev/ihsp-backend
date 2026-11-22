"""What an institution itself says it looks for ("focuses"), sourced from its site.

A focus is a short paraphrase in uz/ru/en, the exact English sentence it rests on
and the page URL. The page must be on the institution's own website (its domain,
a subdomain, or a listed extra domain), so a focus is never a third party's claim.
Only items a curator marked `verified` are shown to students.
"""

import re
import unicodedata
from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import urlsplit

from app.modules.admission.domain.errors import CatalogFactInvalidError

MAX_FOCUSES: Final = 12
QUOTE_MAX: Final = 300
TEXT_MAX: Final = 200
LOCALES: Final = ("en", "ru", "uz")

EXTRA_DOMAINS: Final[Mapping[str, tuple[str, ...]]] = {
    "mit.edu": ("mitadmissions.org",),
}
"""Extra sites an institution owns, keyed by its `website_domain`."""

_SPACES = re.compile(r"\s+")
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def allowed_domains(website_domain: str | None) -> tuple[str, ...]:
    """The institution's own domains: its `website_domain` and the extra ones."""
    if not website_domain:
        return ()
    base = website_domain.strip().lower().removeprefix("www.")
    return (base, *EXTRA_DOMAINS.get(base, ())) if base else ()


def on_domain(url: str, website_domain: str | None) -> bool:
    """True for an https URL on an allowed domain or one of its subdomains."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    if parts.scheme != "https" or not host:
        return False
    return any(
        host == d or host.endswith(f".{d}") for d in allowed_domains(website_domain)
    )


def _squash(text: str) -> str:
    return _SPACES.sub(
        " ", unicodedata.normalize("NFC", text).translate(_QUOTES)
    ).strip()


def quote_in_page(quote: str, page_text: str) -> bool:
    """True when `quote` occurs in the page text (whitespace and quote marks folded)."""
    needle = _squash(quote)
    return bool(needle) and needle in _squash(page_text)


def served_focuses(value: Any, website_domain: str | None) -> list[dict[str, Any]]:
    """The verified items on an allowed domain, from a stored `focuses` value."""
    if not isinstance(value, list):
        return []
    return [
        x
        for x in value
        if isinstance(x, dict)
        and x.get("verified") is True
        and isinstance(x.get("source_url"), str)
        and on_domain(x["source_url"], website_domain)
    ]


def check_domains(value: Any, website_domain: str | None) -> None:
    """Raise `CatalogFactInvalidError` when an item is off the institution's site."""
    for x in value if isinstance(value, list) else []:
        if not on_domain(str(x.get("source_url", "")), website_domain):
            raise CatalogFactInvalidError(
                params={"fact": "focuses", "reason": "source_domain"}
            )
