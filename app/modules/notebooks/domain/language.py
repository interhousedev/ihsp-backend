"""Output languages: names for prompts, the resolution of `auto`, source detection."""

import re
from collections.abc import Iterable
from typing import Final

LANGUAGE_NAMES: Final = {
    "uz": "Uzbek (Latin script)",
    "ru": "Russian",
    "en": "English",
}
DEFAULT_LANGUAGE: Final = "ru"

# Frequent short words that are rare in the other two languages. Uzbek in Cyrillic
# script counts as Uzbek (the output is still written in the Latin script).
_STOPWORDS: Final = {
    "ru": frozenset(
        "и в во не на что с со по это как для из к от за но же у так все она они "
        "мы был была были его её их при также или если только то".split()
    ),
    "uz": frozenset(
        "va bilan uchun bu ham bir deb esa yoki kabi emas edi boʻlgan boʻlib "
        "qilib haqida lekin ammo shu ular biz hamda orqali boʻyicha oʻz "
        "ва билан учун ҳам деб эса ёки каби эмас эди бўлган бўлиб қилиб ҳақида "
        "лекин аммо ҳамда орқали бўйича ўз".split()
    ),
    "en": frozenset(
        "the and of to is in that for are with as on by this it was be from an "
        "which were or has have their these".split()
    ),
}
_APOSTROPHES: Final = str.maketrans({"'": "ʻ", "‘": "ʻ", "’": "ʻ", "`": "ʻ"})
_WORD: Final = re.compile(r"[^\W\d_]+(?:ʻ[^\W\d_]+)*")
MIN_HITS: Final = 8
MIN_LEAD: Final = 1.5  # the winner needs 1.5 times the hits of the runner-up
SAMPLE_CHARS: Final = 6_000


def language_name(code: str) -> str:
    """Return the English name of a language code for a prompt."""
    return LANGUAGE_NAMES.get(code, LANGUAGE_NAMES["en"])


def resolve_language(requested: str | None, locale: str) -> str:
    """`uz|ru|en` as asked; `auto` or nothing follows the user's locale."""
    if requested in LANGUAGE_NAMES:
        return str(requested)
    return locale if locale in LANGUAGE_NAMES else DEFAULT_LANGUAGE


def _hits(text: str) -> dict[str, int]:
    """Stop-word hits per language in a text."""
    counts = dict.fromkeys(_STOPWORDS, 0)
    for word in _WORD.findall(text.casefold().translate(_APOSTROPHES)):
        for code, words in _STOPWORDS.items():
            if word in words:
                counts[code] += 1
    return counts


def detect_language(texts: Iterable[str]) -> str | None:
    """The language most of the texts are written in, or None when unclear.

    Each text (one per source) counts with at most its first 6 000 characters, so a
    long source does not outvote the others.
    """
    total = dict.fromkeys(_STOPWORDS, 0)
    for text in texts:
        for code, hits in _hits(text[:SAMPLE_CHARS]).items():
            total[code] += hits
    ranked = sorted(total.items(), key=lambda item: item[1], reverse=True)
    (best, top), (_, second) = ranked[0], ranked[1]
    if top < MIN_HITS or top < second * MIN_LEAD:
        return None
    return best


_CYRILLIC: Final = re.compile(r"[а-яёўқғҳ]", re.IGNORECASE)
_UZ_CYRILLIC: Final = re.compile(r"[ўқғҳ]", re.IGNORECASE)
_UZ_LATIN: Final = re.compile(
    r"\b\w+[oOgG][ʻʼ'‘’]\w*|\b(?:bo['ʻʼ‘’]yicha|uchun|haqida|tuz|qil|savollar?)\b",
    re.IGNORECASE,
)


def prompt_language(prompt: str | None) -> str | None:
    """The language a short request is written in, or None when unclear.

    The stopword vote needs longer texts; a request such as "сделай тест по
    биологии" is told by its script (Uzbek by its own letters and apostrophes).
    """
    text = (prompt or "").strip()
    if not text:
        return None
    if len(_CYRILLIC.findall(text)) >= 3:
        return "uz" if _UZ_CYRILLIC.search(text) else "ru"
    if _UZ_LATIN.search(text):
        return "uz"
    return detect_language([text])
