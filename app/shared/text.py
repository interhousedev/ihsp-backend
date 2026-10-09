"""Transliteration and normalization helpers."""

import re
import unicodedata

# fmt: off
_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
}
# fmt: on


def transliterate(value: str) -> str:
    """Transliterate Cyrillic (Russian/Uzbek) to Latin; keep other characters."""
    out = []
    for ch in value:
        low = ch.lower()
        lat = _CYR_TO_LAT.get(low)
        if lat is None:
            out.append(ch)
        else:
            out.append(lat.upper() if ch.isupper() and lat else lat)
    return "".join(out)


def slugify(value: str) -> str:
    """Lowercase Latin slug: letters, digits and single hyphens."""
    latin = transliterate(value).lower()
    latin = re.sub(r"[^a-z0-9]+", "-", latin)
    return latin.strip("-")


def normalize_group_name(value: str) -> str:
    """EMIS group name to Latin upper case: '2ТН2' -> '2TN2'."""
    return transliterate(value).upper().replace(" ", "")


def title_case(value: str) -> str:
    """'ALEKSEY' -> 'Aleksey' (EMIS sends upper case Latin names)."""
    return value.strip().capitalize()


# - - - Search normalisation (Uzbek has two scripts) - - -

OKINA = "\u02bb"
"""The letter modifier of `oʻ` and `gʻ` (U+02BB)."""

TUTUQ = "\u02bc"
"""The glottal stop of `maʼno` (U+02BC), also what every stray apostrophe becomes."""

# fmt: off
_UZ_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ё": "yo", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sh", "ъ": TUTUQ, "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o" + OKINA, "қ": "q", "ғ": "g" + OKINA, "ҳ": "h",
}
# fmt: on
_YE_AFTER = frozenset("аеёиоуўэюяыъь")
"""Letters after which `е` is read `ye`, as at the start of a word."""

_APOSTROPHES = "'\u02bb\u02bc\u2018\u2019\u201b`\u00b4\u2032\u02b9"
_APOSTROPHE = re.compile(f"([og]?)([{_APOSTROPHES}])")
_UZBEK = "uz"


def _latin_for(letter: str, previous: str) -> str:
    """The Latin spelling of one lower-case letter (`е` depends on the one before)."""
    if letter == "е":
        starts_word = not previous.isalpha()
        return "ye" if starts_word or previous in _YE_AFTER else "e"
    return _UZ_CYR_TO_LAT.get(letter, letter)


def _cyrillic_to_latin(text: str) -> str:
    """Convert the Cyrillic letters of a lower-case text; other characters stay."""
    out: list[str] = []
    previous = ""
    for letter in text:
        out.append(_latin_for(letter, previous))
        previous = letter
    return "".join(out)


def _one_apostrophe(match: re.Match[str]) -> str:
    """After `o` or `g` an apostrophe is the okina of `oʻ`/`gʻ`, else a tutuq."""
    return match[1] + (OKINA if match[1] else TUTUQ)


def _tidy(text: str) -> str:
    """Collapse runs of whitespace into single spaces and strip the ends."""
    return " ".join(text.split())


def _is_uzbek(language: str) -> bool:
    """True for `uz` and its tags (`uz-Cyrl`, `uz_Latn`), in any case."""
    return re.split("[-_]", language.lower(), maxsplit=1)[0] == _UZBEK


def uz_translit(text: str, *, language: str = _UZBEK) -> str:
    """Bring Uzbek text in either script to one lower-case Latin form for search.

    Cyrillic letters become Latin (`ўзбек` -> `oʻzbek`, `маъно` -> `maʼno`; `е` is
    `ye` at the start of a word and after a vowel or a sign). Every apostrophe variant
    collapses to one character: `oʻ`/`gʻ` take U+02BB, any other apostrophe becomes
    U+02BC. Latin cannot tell `oʻ` from `o`+tutuq, so `оъ` and `o'` meet on `oʻ`. The
    result is idempotent. For other languages (`ru`, `en`) only case and whitespace
    are normalised: Russian is not transliterated.
    """
    if not _is_uzbek(language):
        return _tidy(text.lower())
    lowered = unicodedata.normalize("NFC", text).lower()
    latin = _APOSTROPHE.sub(_one_apostrophe, _cyrillic_to_latin(lowered))
    return _tidy(latin)


def search_normalize(text: str, language: str = _UZBEK) -> str:
    """The form in which a text is stored in `search_text` and a query is compared.

    `uz_translit` already collapses whitespace and strips the ends, so a query typed
    with stray spaces and a stored text with line breaks meet on the same string.
    """
    return uz_translit(text, language=language)
