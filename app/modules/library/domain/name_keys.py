"""Search keys of people's names and tags: one spelling for Latin and Cyrillic.

"Navoiy", "Navoi" and "Навои" must meet on one key, and so must "Qodiriy" and the
Russian "Кадыри". The key is therefore a loose phonetic form, not a faithful
transliteration: Uzbek and Russian Cyrillic become Latin, apostrophes vanish, and
the letters the two scripts disagree on are folded (`q`/`k`, `o`/`a`, `x`/`h`,
`y`/`i`, `c`/`k`, `w`/`v`). The key is only for matching; the name itself is stored as
the user typed it.
"""

import re
import unicodedata

NAME_MAX = 255
TAG_MAX = 40

# fmt: off
_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "s",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o", "қ": "k", "ғ": "g", "ҳ": "h", "ә": "a", "і": "i", "ї": "i",
}
# fmt: on
_DIGRAPHS = (("zh", "j"), ("kh", "h"), ("ts", "s"), ("sh", "s"), ("ch", "#"))
_FOLD = str.maketrans(
    {"q": "k", "c": "k", "x": "h", "w": "v", "o": "a", "y": "i", "e": "a"}
)
_JUNK = re.compile(r"[^a-z0-9 ]+")
_REPEATS = re.compile(r"(.)\1+")


def clean_label(text: str, limit: int = NAME_MAX) -> str:
    """The text with spaces collapsed, cut to `limit` characters."""
    return " ".join(text.split())[:limit].strip()


def _to_latin(text: str) -> str:
    return "".join(_CYRILLIC.get(letter, letter) for letter in text)


def name_key(text: str) -> str:
    """The loose phonetic key of a name or tag (lower case Latin, single spaces).

    `Navoiy`, `Navoi` and `Навои` give `navai`; `Abdulla Qodiriy` and `Абдулла Кадыри`
    give `abdula kadiri`. Digits stay; every other punctuation mark is dropped.
    """
    lowered = unicodedata.normalize("NFC", text).lower()
    latin = _to_latin(lowered)
    for digraph, single in _DIGRAPHS:
        latin = latin.replace(digraph, single)
    latin = latin.translate(_FOLD).replace("#", "c")
    latin = _JUNK.sub("", latin.replace("-", " "))
    return " ".join(_REPEATS.sub(r"\1", latin).split())
