"""Removes the model's leading meta narration from an answer.

Some models open with notes about the request ("The student gave the marks directly,
so no tools are needed.") although the prompt forbids it. Only whole sentences at the
very start are removed, and only when a sentence talks about the user, the request or
the tools in the third person. Anything else, in particular a sentence where "the
student" is the topic of the answer, stays. An answer that would become empty is kept.
"""

import re
from typing import Final

from app.shared.ai.answer_language import detect_language

MAX_NARRATION_CHARS: Final = 400  # a longer sentence is content, not a note
_MAX_HELD_CHARS: Final = 600

_PERSON_WORDS: Final = re.compile(
    r"\b(?:student|студент\w*|ученик\w*|ученица\w*|o['ʼʻ’‘`]?quvchi\w*|talaba\w*)\b",
    re.IGNORECASE | re.UNICODE,
)
_PERSON_EN: Final = r"(?:the\s+(?:student|user|teacher)|this\s+student)"
_PERSON_RU: Final = r"(?:студент(?:ка)?|ученик|ученица|пользователь|учитель)"
_PERSON_UZ: Final = r"(?:o['ʼʻ’‘`]?quvchi|talaba|foydalanuvchi)"

_META_OBJECT_EN: Final = (
    r"(?:table|chart|plan|comparison|answer|question|request|help|list|summary|"
    r"explanation|marks|grades|numbers|data|tools?|directly|in\s+(?:uzbek|russian|"
    r"english)|look(?:ing)?\s+(?:anything\s+)?up)"
)
_PATTERNS: Final = tuple(
    re.compile(p, re.IGNORECASE | re.UNICODE)
    for p in (
        # "The student gave the marks directly", "The user asks for a table"
        rf"^{_PERSON_EN}'?s?\s+(?:last\s+message\s+|message\s+|request\s+)?"
        r"(?:is\s+asking|is\s+requesting|asks?|asked|wants?|wanted|requests?|requested|"
        r"gave|has\s+given|provided|has\s+provided|wrote|is\s+written|needs?|"
        rf"is\s+in|did\s+not|didn't|does\s+not|doesn't)\b.*{_META_OBJECT_EN}",
        # "Since the student gave ...", "Because the user asked ..."
        rf"^(?:since|because|as|given\s+that)\s+{_PERSON_EN}\b.*"
        r"(?:gave|given|provided|asked|asks|wants?|wrote|tools?|look)",
        r"^(?:i\s+(?:do\s+not|don't|won't)\s+need\s+(?:to\s+\w+\s+)?(?:any\s+)?tools?"
        r"|no\s+tools?\s+(?:are|is|call\w*)\b|tools?\s+(?:are|is)\s+not\s+(?:needed|"
        r"required)|without\s+(?:using\s+)?(?:any\s+)?tools?\b)",
        r"^this\s+(?:is\s+)?(?:a\s+)?(?:simple|direct|straightforward|plain)\s+"
        r"(?:question|request)\b",
        r"^the\s+(?:request|question)\s+is\s+(?:for|about|to)\b",
        r"^an?\s+(?:table|chart|block|diagram)\s+is\s+(?:requested|needed|required|"
        r"appropriate)\b",
        r"^(?:таблица|график|диаграмма|блок)\s+(?:\S+\s+)?(?:нужн\w*|требует\w*)\b",
        r"^let\s+me\s+(?:compute|calculate|think|check|look|use|fetch|see)\b",
        r"^keep\s+(?:one|a)\s+short\s+sentence\b",
        r"^i(?:'ll|\s+will)\s+(?:look|check|search|find|compute|calculate)\b",
        r"^(?:сейчас\s+)?(?:посмотрю|проверю|посчитаю|поищу|найду|вычислю)\b",
        r"^(?:hozir\s+)?(?:tekshiraman|qarab\s+chiqaman|hisoblayman|hisoblab\s+"
        r"chiqaman)\b",
        # Russian
        rf"^{_PERSON_RU}\s+(?:\S+\s+){{0,2}}(?:дал|дала|предоставил|предоставила|"
        r"просит|"
        r"попросил|попросила|хочет|спрашивает|спросил|спросила|написал|написала|"
        r"указал|указала|запросил|запросила)\b",
        r"^(?:инструменты?\s+(?:не\s+нуж|не\s+требу)|без\s+инструментов\b|"
        r"запрос\s+(?:на|о)\b)",
        # Uzbek
        rf"^{_PERSON_UZ}\s+(?:\S+\s+){{0,6}}?\S*(?:so['ʼʻ’‘`]?ra\w*|ber(?:di|gan)\w*|"
        r"yoz(?:di|gan)\w*|xohla\w*|ko['ʼʻ’‘`]?rsat(?:di|gan)\w*)\b",
        r"^(?:vositalar?\s+(?:kerak|talab)|vositalarsiz\b)",
    )
)
# First words that can open a note; any other start is released at once when streaming.
_OPENERS: Final = re.compile(
    r"^(?:the|this|since|because|as|given|i|no|tools?|without|a|an|let|keep|таблица|"
    r"график|диаграмма|блок|студент\w*|учитель|сейчас|посмотрю|проверю|посчитаю|"
    r"поищу|найду|вычислю|hozir|tekshiraman|qarab|hisoblayman|hisoblab|"
    r"ученик\w*|ученица|пользователь|инструмент\w*|без|запрос|o['ʼʻ’‘`]?quvchi\w*|"
    r"talaba\w*|foydalanuvchi\w*|vosita\w*)\b",
    re.IGNORECASE | re.UNICODE,
)
_SENTENCE_END: Final = re.compile(r"[.!?…:](?:\s+|$)|\n")
_FENCE: Final = "```"
_WORKED_SUM: Final = re.compile(
    r"(?:\(\s*\d[\d\s+.,]*\)\s*/\s*\d+|\d+(?:[.,]\d+)?(?:\s*\+\s*\d+(?:[.,]\d+)?)+)"
    r"\s*=\s*(?=\d)"
)
_PROTECTED_SPANS: Final = re.compile(r"(```.*?(?:```|\Z)|`[^`\n]*`|\$[^$\n]*\$)", re.S)
_SHOWS_WORK: Final = re.compile(
    r"\b(?:how|why|explain|solve|steps?|show\s+the\s+work\w*|как|почему|объясн\w*|"
    r"реши\w*|шаг\w*|решени\w*|qanday|nega|tushuntir\w*|yech\w*|bosqich\w*)\b",
    re.IGNORECASE | re.UNICODE,
)


def _first_sentence(text: str) -> tuple[str, str] | None:
    """Split off a finished first sentence; None when it has not ended yet."""
    match = _SENTENCE_END.search(text)
    if match is None:
        return None
    return text[: match.end()], text[match.end() :]


def mentions_a_student(text: str) -> bool:
    """True when "the student" can be the topic of the conversation, not the user."""
    return _PERSON_WORDS.search(text) is not None


def _is_narration(sentence: str, about_student: bool) -> bool:
    body = sentence.strip()
    if not body or len(body) > MAX_NARRATION_CHARS or _FENCE in body:
        return False
    if not about_student and _PERSON_WORDS.search(body):
        return False
    return any(pattern.search(body) for pattern in _PATTERNS)


def _english_working_notes(
    paragraph: str, following: str, language: str | None
) -> bool:
    """True for an English paragraph right after a note, in a non-English answer."""
    if language in (None, "en") or not following or _FENCE in paragraph:
        return False
    return detect_language(paragraph) in ("en", None)


def _without_working_notes(text: str, language: str | None) -> str:
    rest = text
    while True:
        paragraph, _, following = rest.partition("\n\n")
        if not _english_working_notes(paragraph, following, language):
            return rest
        rest = following.lstrip()


def _without_note_paragraphs(text: str, about_student: bool) -> str:
    """Drop later paragraphs of notes, up to the first block."""
    head, fence, tail = text.partition(_FENCE)
    kept = [
        paragraph
        for paragraph in head.split("\n\n")
        if not _all_notes(paragraph, about_student)
    ]
    return "\n\n".join(kept) + fence + tail


def _all_notes(paragraph: str, about_student: bool) -> bool:
    rest = paragraph.strip()
    if not rest:
        return False
    while rest:
        split = _first_sentence(rest)
        sentence, after = split if split is not None else (rest, "")
        if not _is_narration(sentence, about_student):
            return False
        rest = after.strip()
    return True


def strip_narration(
    text: str, *, about_student: bool = True, language: str | None = None
) -> str:
    """The answer without leading narration sentences.

    `about_student` False keeps sentences about a student: in an Administration chat
    or a question about a student they are the content, not a note about the user.
    With `language` (of the answer) English paragraphs after a removed note go too:
    they are the rest of the model's notes. Without a note nothing else is touched,
    so a requested English text in an Uzbek answer stays.
    """
    rest = text.lstrip()
    removed = False
    while True:
        split = _first_sentence(rest)
        sentence, after = split if split is not None else (rest, "")
        if not _is_narration(sentence, about_student):
            break
        removed = True
        rest = after.lstrip()
        if not rest:
            return text  # nothing else was written: keep what there is
    if not removed:
        return text
    rest = _without_working_notes(rest, language)
    return _without_note_paragraphs(rest, about_student) or rest


def strip_worked_sums(text: str, asked: str) -> str:
    """Final numbers only: `(5 + 4) / 2 = 4,5` becomes `4,5` outside code and maths.

    A question that asks for the way (how, why, solve, steps) keeps its working.
    """
    if _SHOWS_WORK.search(asked):
        return text
    parts = _PROTECTED_SPANS.split(text)
    parts[::2] = [_WORKED_SUM.sub("", part) for part in parts[::2]]
    return "".join(parts)


class NarrationFilter:
    """The same removal over a stream: holds the start until a decision is possible.

    Text is held only while it can still be a note. The first sentence that is not
    one, or an opening word that cannot start one, releases everything, and from
    then on the pieces pass through untouched.
    """

    def __init__(
        self, *, about_student: bool = True, language: str | None = None
    ) -> None:
        """Start undecided with nothing held (the options: see `strip_narration`)."""
        self._about_student = about_student
        self._language = language
        self._held = ""
        self._open = False
        self._removed = False

    def feed(self, piece: str) -> str:
        """Take a piece of the stream; return the text that may go out now."""
        if self._open:
            return piece
        self._held = (self._held + piece).lstrip()
        return self._drain()

    def _drain(self) -> str:
        while self._held:
            if not self._may_be_narration():
                return self._after_notes()
            split = _first_sentence(self._held)
            if split is None:
                return ""  # the sentence is still being written
            sentence, after = split
            if not _is_narration(sentence, self._about_student):
                return self._after_notes()
            self._removed = True
            self._held = after.lstrip()
        return ""

    def _after_notes(self) -> str:
        """Release the text, once the paragraphs after a note were judged."""
        if not self._removed or self._language in (None, "en"):
            return self._release()
        while True:
            paragraph, _, following = self._held.partition("\n\n")
            if not following and len(self._held) <= _MAX_HELD_CHARS:
                return ""  # the paragraph is still being written
            if not _english_working_notes(paragraph, following, self._language):
                return self._release()
            self._held = following.lstrip()

    def _may_be_narration(self) -> bool:
        if len(self._held) > _MAX_HELD_CHARS:
            return False
        words = self._held.split(maxsplit=1)
        word = words[0].rstrip(",.:;!?") if words else ""
        complete = len(words) > 1 or self._held[-1:].isspace()
        return not complete or bool(_OPENERS.match(word))

    def _release(self) -> str:
        out, self._held = self._held, ""
        self._open = True
        return out

    def finish(self) -> str:
        """The end of the stream: whatever is still held and is not a note."""
        out, self._held = self._held, ""
        self._open = True
        return "" if _is_narration(out, self._about_student) else out
