"""Search queries and the text items are matched on (doc § 3.7).

Uzbek has two scripts, so `items.search_text` and `item_pages.text_norm` of Uzbek items
are Latin-normalised, and a query is tried in two forms: as typed (lower-cased, which
finds Russian and English items) and Latin-normalised (which finds Uzbek items typed
in either script). Russian and English items are never transliterated.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.library.domain.enums import ItemLanguage
from app.shared.text import search_normalize

MAX_QUERY_CHARS = 200
MAX_QUERY_TOKENS = 8

_WORD = re.compile(r"\w+")
_UZBEK_SCRIPTS = frozenset(
    {ItemLanguage.UZ_LATN, ItemLanguage.UZ_CYRL, ItemLanguage.QQ}
)


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    """A query ready for SQL.

    `raw` is the lower-cased text (for trigram similarity on titles); `forms` are the
    distinct spellings tried; `tsquery` is the text for `to_tsquery('simple', ...)`
    with every word quoted, so user input is never tsquery syntax.
    """

    raw: str
    forms: tuple[str, ...]
    tsquery: str


def item_search_language(language: ItemLanguage) -> str:
    """The code `search_normalize` takes: `uz` for the Uzbek scripts, else as is."""
    if language in _UZBEK_SCRIPTS:
        return "uz"
    return language.value


def build_search_text(
    *,
    language: ItemLanguage,
    title: str,
    subtitle: str | None,
    authors: Sequence[str],
    description: str | None,
) -> str:
    """Title, subtitle, authors and description in the item's search form."""
    parts = [title, subtitle or "", *authors, description or ""]
    joined = " ".join(part for part in parts if part)
    return search_normalize(joined, item_search_language(language))


def _tokens(form: str) -> list[str]:
    return _WORD.findall(form)[:MAX_QUERY_TOKENS]


def _form_query(form: str) -> str | None:
    tokens = _tokens(form)
    if not tokens:
        return None
    quoted = [f"'{token}'" for token in tokens]
    quoted[-1] += ":*"
    return "(" + " & ".join(quoted) + ")"


def parse_query(text: str) -> ParsedQuery | None:
    """Parse what the user typed; None when there is nothing to search for."""
    clipped = text[:MAX_QUERY_CHARS]
    raw = search_normalize(clipped, "ru")
    forms = tuple(dict.fromkeys([raw, search_normalize(clipped, "uz")]))
    queries = [q for q in (_form_query(form) for form in forms) if q]
    if not queries:
        return None
    return ParsedQuery(raw=raw, forms=forms, tsquery=" | ".join(queries))
