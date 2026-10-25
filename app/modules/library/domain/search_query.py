"""Search queries and the text items are matched on (doc § 3.7).

Uzbek has two scripts, so `items.search_text` and `item_pages.text_norm` of Uzbek items
are Latin-normalised, and a query is tried in two forms: as typed (lower-cased, which
finds Russian and English items) and Latin-normalised (which finds Uzbek items typed
in either script). Russian and English items are never transliterated.

People also type the letters Uzbek Cyrillic spells with a diacritic as their plain
neighbours: Қ as К, Ғ as Г, Ў as У, Ҳ as Х. After normalisation these are `q`/`k`,
`gʻ`/`g`, `oʻ`/`u` and `x`/`h`. The stored text keeps its own spelling, so a query
matches every spelling of those letters (`match`) while `tsquery` stays as typed.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.library.domain.enums import ItemLanguage
from app.shared.text import OKINA, search_normalize

MAX_QUERY_CHARS = 200
MAX_QUERY_TOKENS = 8
MAX_SPELLINGS = 16

_WORD = re.compile(r"\w+")
_UNIT = re.compile(f"o{OKINA}|g{OKINA}|.", re.DOTALL)
_UZBEK_SCRIPTS = frozenset(
    {ItemLanguage.UZ_LATN, ItemLanguage.UZ_CYRL, ItemLanguage.QQ}
)
# Each letter (or `oʻ`/`gʻ` pair) with the letters it may stand for; the letter first.
_SAME_LETTER = {
    "k": ("k", "q"),
    "q": ("q", "k"),
    "h": ("h", "x"),
    "x": ("x", "h"),
    "g": ("g", f"g{OKINA}"),
    f"g{OKINA}": (f"g{OKINA}", "g"),
    "u": ("u", f"o{OKINA}"),
    f"o{OKINA}": (f"o{OKINA}", "u"),
}


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    """A query ready for SQL.

    `raw` is the lower-cased text (for trigram similarity on titles); `forms` are the
    distinct spellings tried; `tsquery` is the text for `to_tsquery('simple', ...)`
    with every word quoted, so user input is never tsquery syntax. `match` is the same
    text with every folded spelling of each word added (`к` also finds `қ`), and is what
    the search runs on.
    """

    raw: str
    forms: tuple[str, ...]
    tsquery: str
    match: str


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


def spellings(text: str, limit: int = MAX_SPELLINGS) -> list[str]:
    """`text` with each folded letter swapped for the letters it may stand for.

    `кодирий` gives `kodiriy` and `qodiriy` (and so on for every folded letter); the
    text itself comes first. At most `limit` spellings are returned.
    """
    units = _UNIT.findall(text)
    out = ["".join(units)]
    # The text, then one swapped letter at a time, so every position gets a spelling
    # even when a long query has more folded letters than `limit` allows.
    for i, unit in enumerate(units):
        for other in _SAME_LETTER.get(unit, ())[1:]:
            out.append("".join([*units[:i], other, *units[i + 1 :]]))
    return out[:limit]


def _form_query(form: str) -> str | None:
    tokens = _tokens(form)
    if not tokens:
        return None
    quoted = [f"'{token}'" for token in tokens]
    quoted[-1] += ":*"
    return "(" + " & ".join(quoted) + ")"


def _word_match(token: str, *, prefix: bool) -> str:
    quoted = [
        f"'{spelling}'" + (":*" if prefix else "") for spelling in spellings(token)
    ]
    return quoted[0] if len(quoted) == 1 else "(" + " | ".join(quoted) + ")"


def _form_match(form: str) -> str | None:
    tokens = _tokens(form)
    if not tokens:
        return None
    last = len(tokens) - 1
    words = [_word_match(token, prefix=i == last) for i, token in enumerate(tokens)]
    return "(" + " & ".join(words) + ")"


def parse_query(text: str) -> ParsedQuery | None:
    """Parse what the user typed; None when there is nothing to search for."""
    clipped = text[:MAX_QUERY_CHARS]
    raw = search_normalize(clipped, "ru")
    forms = tuple(dict.fromkeys([raw, search_normalize(clipped, "uz")]))
    queries = [q for q in (_form_query(form) for form in forms) if q]
    matches = [m for m in (_form_match(form) for form in forms) if m]
    if not queries:
        return None
    return ParsedQuery(
        raw=raw,
        forms=forms,
        tsquery=" | ".join(queries),
        match=" | ".join(matches),
    )
