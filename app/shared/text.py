"""Transliteration and normalization helpers."""

import re

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
