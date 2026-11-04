"""The letters of an Uzbek answer: ʼ (U+02BC) in oʼ, gʼ and the tutuq belgisi.

Models keep writing ' ‘ ’ ʻ whatever the prompt says, so the final text is corrected
here. Code, addresses and formulas stay as written; an OpenUI block is corrected only
in its text, since its structure has no apostrophe between two letters.
"""

import re
from typing import Final

from app.shared.ai.answer_language import detect_language

_OPENUI: Final = "```openui"
_LETTER: Final = r"[^\W\d_]"
_APOSTROPHE: Final = re.compile(rf"(?<={_LETTER})['‘’`ʻ](?={_LETTER})")
_PROTECTED: Final = re.compile(
    r"```.*?(?:```|\Z)|(?<!`)`(?!`)[^`\n]*`|https?://\S+|\$[^$\n]*\$",
    re.DOTALL,
)
_FENCED: Final = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
_STRING: Final = re.compile(r'"([^"\n]*)"')
_FENCE_OR_TICK: Final = re.compile(r"```|`")
_LAST_SPACE: Final = re.compile(r"\s(?=\S*\Z)")


def _letters(text: str) -> str:
    return _APOSTROPHE.sub("ʼ", text)


def normalize_uzbek(text: str) -> str:
    """Correct the apostrophes of Uzbek text outside protected parts."""
    parts: list[str] = []
    position = 0
    for match in _PROTECTED.finditer(text):
        kept = match.group(0)
        if kept.startswith(_OPENUI):  # its text is corrected, its addresses are not
            body = kept[len(_OPENUI) :]
            kept = _OPENUI + normalize_uzbek(body)
        parts.extend((_letters(text[position : match.start()]), kept))
        position = match.end()
    parts.append(_letters(text[position:]))
    return "".join(parts)


def normalize_answer(text: str) -> str:
    """Correct a finished answer when it is in Uzbek; any other text stays."""
    prose = _FENCED.sub(" ", text)
    language = detect_language(prose)
    if language is None:  # the answer is mostly a block: its strings decide
        language = detect_language(" ".join(_STRING.findall(text)))
    return normalize_uzbek(text) if language == "uz" else text


class UzbekStream:
    """`normalize_uzbek` over a stream: holds the unfinished last word.

    It keeps whether the text is inside inline code or a fence, since those can span
    several words.
    """

    def __init__(self) -> None:
        """Start outside any code."""
        self._held = ""
        self._code = ""

    def feed(self, delta: str) -> str:
        """Add a piece; return the finished words."""
        self._held += delta
        match = _LAST_SPACE.search(self._held)
        if match is None:
            return ""
        ready, self._held = self._held[: match.end()], self._held[match.end() :]
        return self._release(ready)

    def finish(self) -> str:
        """Return what is still held."""
        rest, self._held = self._held, ""
        return self._release(rest)

    def _release(self, text: str) -> str:
        words = re.split(r"(\s+)", text)
        return "".join(self._word(word) for word in words)

    def _word(self, word: str) -> str:
        was_code = bool(self._code)
        for tick in _FENCE_OR_TICK.findall(_APOSTROPHE.sub("", word)):
            if not self._code:
                self._code = tick
            elif self._code == tick:
                self._code = ""
        if was_code or self._code:
            return word
        return normalize_uzbek(word)
