"""Which language an answer is written in: the user's message, then the locale.

A small, deterministic guess among the three languages of the platform. It decides
only when the message clearly shows a language; short or mixed text, numbers and code
fall back to the user's locale.
"""

import re
from typing import Final

LANGUAGE_NAMES: Final = {"uz": "Uzbek (Latin script)", "ru": "Russian", "en": "English"}

UZBEK_LETTERS_RULE: Final = (
    "Write oʼ, gʼ and tutuq belgisi with ʼ (U+02BC), never ' ‘ ’ or ʻ."
)

_WORD: Final = re.compile(r"[^\W\d_]+(?:['ʼʻ’‘`][^\W\d_]+)*", re.UNICODE)
_CYRILLIC: Final = re.compile(r"[Ѐ-ӿ]")
_UZBEK_CYRILLIC: Final = re.compile(r"[ўқғҳЎҚҒҲ]")
_UZBEK_LETTERS: Final = re.compile(r"\b\w*[og]['ʼʻ’‘`]\w*", re.IGNORECASE)
_UZBEK_ENDING: Final = re.compile(
    r"\w{3,}(?:lar|larni|larga|lardan|ning|ingiz|imiz|ingizni|imni|ni|ga|dan|da|mi|"
    r"man|miz|chi|cha|moq|yapti|ayapti|adi|ydi)$"
)
_UZBEK_WORDS: Final = frozenset("""
    va uchun bilan qanday nima nega qachon qayerda kim men menga meni mening sen siz
    sizga u bu shu ham lekin yoki emas bor yoʻq yo'q kerak bugun ertaga kecha hafta
    dars darslar baho baholar fan fanlar fanlarni jadval jadvalda jadvalni reja
    qil qiling ber bering ayting tushuntir tushuntiring yordam salom rahmat haqida
    necha qancha uy vazifa imtihon oʻquvchi o'quvchi maktab tayyorlanish grafik
    koʻrsat ko'rsat koʻrsating ko'rsating solishtir solishtiring tuz tuzing
    """.split())
_ENGLISH_WORDS: Final = frozenset("""
    the a an and or but of to in on at for with from is are was were be been do does
    did have has had what when where why how who which my me i you your it this that
    these those can could should would will please give make show tell compare draw
    explain help need want table chart plan marks homework
    """.split())
_MIN_SCORE: Final = 1
_MAX_SCAN: Final = 2000


def detect_language(text: str) -> str | None:
    """Return "uz", "ru" or "en" when the text clearly shows it, otherwise None."""
    sample = text[:_MAX_SCAN]
    words = [w.casefold() for w in _WORD.findall(sample)]
    if not words:
        return None
    cyrillic = sum(1 for w in words if _CYRILLIC.search(w))
    if cyrillic * 2 > len(words):
        return "uz" if _UZBEK_CYRILLIC.search(sample) else "ru"
    return _latin_language(words, sample)


def _latin_language(words: list[str], sample: str) -> str | None:
    english = sum(1 for w in words if w in _ENGLISH_WORDS)
    uzbek = sum(1 for w in words if w in _UZBEK_WORDS)
    uzbek += sum(1 for w in words if w not in _UZBEK_WORDS and _uzbek_shape(w))
    uzbek += 2 * len(_UZBEK_LETTERS.findall(sample))
    if uzbek < _MIN_SCORE and english < _MIN_SCORE:
        return None
    if uzbek == english:
        return None
    return "uz" if uzbek > english else "en"


def _uzbek_shape(word: str) -> bool:
    return word not in _ENGLISH_WORDS and bool(_UZBEK_ENDING.fullmatch(word))


def answer_language(text: str, locale: str) -> str:
    """The language of the answer: the message's, or the locale when it is unclear."""
    return detect_language(text) or (locale if locale in LANGUAGE_NAMES else "en")


def language_line(language: str) -> str:
    """The dedicated last line of a system prompt."""
    name = LANGUAGE_NAMES.get(language, LANGUAGE_NAMES["en"])
    line = (
        f"Write all text the user reads in {name}, including text before tool calls, "
        "even when tools or sources use another language."
    )
    return f"{line} {UZBEK_LETTERS_RULE}" if language == "uz" else line
