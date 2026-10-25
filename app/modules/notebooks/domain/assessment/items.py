"""Item writing: the batch task, the item schemas and the self-containment rules."""

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from typing import Final

from app.modules.notebooks.domain.assessment.blueprint import ItemSpec

from pydantic import BaseModel, Field

STIMULUS_MAX_WORDS: Final = 120
VERIFY_SCHEMA_NAME: Final = "nb_item_verify"
VERIFY_MAX_TOKENS: Final = 1_500

# Words that point at text the student never sees (en, ru, uz). A stimulus in the
# item itself makes "the passage" legitimate.
_UNSEEN: Final = re.compile(
    r"\b(?:according to the (?:text|passage|author|source|list|table|article|"
    r"reading|chapter|document)|(?:in|from) the (?:passage|text|excerpt|source|"
    r"list|article|reading|chapter|document)|the (?:passage|author|excerpt) "
    r"(?:says|states|notes|argues|suggests|mentions|claims)|(?:in |at )?line \d+|"
    r"(?:in|from|see) paragraph \d+|see above|mentioned above|"
    r"(?:all|none) of the above|"
    r"(?:the )?(?:sat )?vocabulary list|"
    r"согласно тексту|в тексте|в отрывке|по тексту|автор (?:отмечает|пишет|"
    r"считает|утверждает)|в строке \d+|в абзаце \d+|из списка|"
    r"matnga ko['‘’]ra|matnda|parchada|muallif (?:ta['‘’]kidlaydi|yozadi))\b",
    re.IGNORECASE,
)
_ALWAYS_BAD: Final = re.compile(
    r"\b(?:(?:all|none) of the above|все (?:вышеперечисленное|перечисленные)|"
    r"line \d+|в строке \d+)\b",
    re.IGNORECASE,
)


def stem_key(text: str) -> str:
    """Normalised stem for duplicate detection (case, punctuation, LaTeX spacing)."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    kept = "".join(
        ch if not unicodedata.category(ch).startswith("P") else " " for ch in folded
    )
    return " ".join(kept.split())


def item_key(stem: str, stimulus: str = "") -> str:
    """Duplicate key of an item: a generic stem over another stimulus is new."""
    return stem_key(f"{stimulus}\n{stem}")


# Options are shuffled after writing, so a letter in the explanation goes stale.
_OPTION_LETTER: Final = re.compile(
    r"\b(?i:options?|choices?|answers?|вариант\w*|javob|variant)\s*\(?"
    r"(?P<letter>[A-HА-Д])\b\)?"
)
QUOTED_OPTION_CHARS: Final = 60


def unlettered(explanation: str, options: Sequence[Mapping[str, object]]) -> str:
    """The explanation with "option B" replaced by the quoted text of option B.

    Letters of unknown options stay (`option_letter_problem` rejects them).
    """
    texts = {
        str(o.get("id") or "").casefold(): str(o.get("text") or "") for o in options
    }

    def quote(found: re.Match[str]) -> str:
        text = texts.get(found.group("letter").casefold())
        if not text:
            return found.group(0)
        lead = "The" if found.group(0)[0].isupper() else "the"
        return f"{lead} option «{' '.join(text.split())[:QUOTED_OPTION_CHARS]}»"

    return _OPTION_LETTER.sub(quote, explanation)


def option_letter_problem(explanation: str) -> str | None:
    """Why an explanation names options by letter, or None."""
    found = _OPTION_LETTER.search(explanation)
    if found is None:
        return None
    return (
        f"the explanation names an option by letter ('{found.group(0)}'); options "
        "are shuffled, quote the option text instead"
    )


# - - - Copies of source problems - - -

COPY_THRESHOLD: Final = 0.85  # normalised similarity of a copy
COPY_SAME_NUMBERS: Final = 0.6  # similarity of a copy that keeps 2+ numbers
PASSAGE_MIN_CHARS: Final = 60  # a source line long enough to be a passage
COPY_MIN_CHARS: Final = 25  # shorter pool entries are too generic to compare
_NUMBERED: Final = re.compile(
    r"^\s*(?:\d{1,3}[.)]|[PpQq]\d{1,3}[.)]|(?:problem|question|задача|masala)"
    r"\s*\d{1,3}[.):]?)\s*",
    re.IGNORECASE,
)
_ANSWER: Final = re.compile(r"\s*(?:answer|ответ|javob)\s*:.*$", re.IGNORECASE)
_NUMBER: Final = re.compile(r"\d+(?:[.,]\d+)?")
_OPTION_LINE: Final = re.compile(r"^\s*[A-Ha-h][.)]\s")
_REVIEW: Final = re.compile(
    r"\bsource review\b|\b(?:same|original|exact) (?:questions|problems)\b|"
    r"\bas (?:written|in the source)\b|\bте же (?:задачи|вопросы)\b|"
    r"\bисходные (?:задачи|вопросы)\b|\basl (?:savollar|masalalar)\b",
    re.IGNORECASE,
)


def copy_key(text: str) -> str:
    """Text for copy detection: case and spacing folded; numbers and math kept."""
    flat = _ANSWER.sub("", _NUMBERED.sub("", text))
    flat = re.sub(r"[$\\{}]|\btext\b\s*:", " ", flat.casefold())
    return re.sub(r"\s*([=+*/^<>(),.?:;-])\s*", r"\1", " ".join(flat.split()))


def source_items(texts: Sequence[str]) -> list[str]:
    """Copy keys of the problems and questions the sources state.

    A numbered line is one item; any other paragraph is one item and each of its
    passage lines another (questions stay generic; headings, option lines and
    answers are left out).
    """
    pool: list[str] = []
    for text in texts:
        for block in re.split(r"\n\s*\n", text):
            lines = [line for line in block.splitlines() if line.strip()]
            numbered = [line for line in lines if _NUMBERED.match(line)]
            body = [
                line
                for line in lines[1:] or lines
                if not _OPTION_LINE.match(line) and not _ANSWER.match(line)
            ]
            # the whole item, and each of its lines (a passage reused alone)
            passages = [
                line
                for line in body
                if len(line) >= PASSAGE_MIN_CHARS and not line.rstrip().endswith("?")
            ]
            parts = numbered or [" ".join(body), *passages]
            pool.extend(k for k in map(copy_key, parts) if len(k) >= COPY_MIN_CHARS)
    return list(dict.fromkeys(pool))


def wants_source_review(prompt: str | None) -> bool:
    """True when the request asks for the source questions themselves."""
    return bool(prompt and _REVIEW.search(prompt))


def copied_source(
    text: str, pool: Sequence[str], threshold: float = COPY_THRESHOLD
) -> str | None:
    """Why an item copies a source problem, or None.

    A copy reads almost the same and keeps the source's numbers; new numbers in
    the same frame make a new problem.
    """
    key = copy_key(text)
    if len(key) < COPY_MIN_CHARS:
        return None
    numbers = sorted(_NUMBER.findall(key))
    for entry in pool:
        if sorted(_NUMBER.findall(entry)) != numbers:
            continue
        # the same two or more numbers: a reworded stem is still the same problem
        limit = COPY_SAME_NUMBERS if len(numbers) >= 2 else threshold
        matcher = SequenceMatcher(None, key, entry, autojunk=False)
        if matcher.real_quick_ratio() < limit or matcher.quick_ratio() < limit:
            continue
        if matcher.ratio() >= limit:
            return (
                "copies a source problem; keep its type but change the numbers "
                "or the context"
            )
    return None


def stimulus_words(text: str) -> int:
    """Words of a stimulus outside its visual blocks."""
    return len(re.sub(r"```.*?(?:```|$)", " ", text, flags=re.DOTALL).split())


def unseen_reference(stem: str, stimulus: str) -> str | None:
    """Why a stem depends on text the student cannot see, or None.

    With a stimulus present only the always-bad phrases count ("line 3", "all of
    the above"); without one any pointer at a passage, author or list does.
    """
    pattern = _ALWAYS_BAD if stimulus.strip() else _UNSEEN
    found = pattern.search(stem)
    if found is None:
        return None
    return f"refers to unseen text ('{found.group(0)}'); make the item self-contained"


# Currency written as a bare "$60" opens a LaTeX span that swallows prose.
_MATH_SPAN: Final = re.compile(r"(?<!\\)\$([^$]+?)(?<!\\)\$")
_PROSE: Final = re.compile(r"(?:\b[A-Za-z]{3,}\b\s+){2}\b[A-Za-z]{3,}\b")


def latex_problem(text: str) -> str | None:
    r"""Why the inline math of an item breaks, or None.

    A `$...$` span holding running prose ("$60 and the monthly fee is $") means an
    unescaped dollar sign; `\text{...}` inside a span is allowed.
    """
    for span in _MATH_SPAN.findall(text):
        if _PROSE.search(re.sub(r"\\[a-zA-Z]+\{[^}]*\}", " ", span)):
            return "a bare $ opens LaTeX math around prose; write money as \\$60"
    return None


def stimulus_problem(spec: ItemSpec | None, stimulus: str) -> str | None:
    """Why the stimulus is missing or too long, or None."""
    words = stimulus_words(stimulus)
    if spec is not None and spec.stimulus and words == 0:
        return "this item needs its passage excerpt in `stimulus`"
    if words > STIMULUS_MAX_WORDS:
        return f"`stimulus` is longer than {STIMULUS_MAX_WORDS} words"
    return None


# - - - Schemas of the batch call (no nullable fields: see `strict.py`) - - -


class QuizOptionOut(BaseModel):
    """An answer option."""

    id: str
    text: str


class QuizItemOut(BaseModel):
    """A quiz item of a batch."""

    spec_id: str = Field(description="the blueprint slot id, e.g. b3")
    stimulus: str = Field(
        description="the passage excerpt (<= 120 words) the item needs, or ''"
    )
    type: str
    prompt: str
    options: list[QuizOptionOut]
    correct: list[str]
    explanation: str
    hint: str
    difficulty: str
    topic: str
    refs: list[str]


class QuizBatchOut(BaseModel):
    """A batch of quiz items."""

    title: str
    questions: list[QuizItemOut]


class CardItemOut(BaseModel):
    """A flash card of a batch."""

    spec_id: str = Field(description="the blueprint slot id, e.g. b3")
    front: str
    back: str
    hint: str
    topic: str
    refs: list[str]


class CardBatchOut(BaseModel):
    """A batch of flash cards."""

    title: str
    cards: list[CardItemOut]


class VerdictOut(BaseModel):
    """The checker's verdict on one item."""

    id: str
    self_contained: bool
    answer: list[str] = Field(description="the option ids you find correct")
    single_answer: bool = Field(description="exactly one defensible key")
    reason: str


class VerifyOut(BaseModel):
    """The checker's document."""

    verdicts: list[VerdictOut]


# - - - Prompts - - -

RULES: Final = (
    "Hard rules for every item:\n"
    "1. Self-contained: a student who never saw the sources can answer it. Never "
    "write 'according to the text', 'the passage', 'the author notes', 'the list', "
    "'line 3', 'above'.\n"
    "2. If an item needs a passage (reading, evidence, word in context), copy the "
    f"needed excerpt (at most {STIMULUS_MAX_WORDS} words) into `stimulus`; "
    "otherwise `stimulus` is ''.\n"
    "3. Exactly one defensible answer; distractors are plausible, of the same "
    "type and length (other words from the same list, results of typical "
    "mistakes); never 'all/none of the above'.\n"
    "4. A short explanation of why the key is right.\n"
    "5. Math in LaTeX: $...$ inline. Money is written with an escaped dollar "
    "sign (\\$60), never a bare $.\n"
    "6. Every slot gets one item; `spec_id` names the slot. Keep `refs` to the "
    "passages you used, but the item must not depend on them being read.\n"
    "7. Never copy a solved problem or answered question from the sources: keep "
    "its type and skill but change the numbers or the context (the student has "
    "seen its answer).\n"
    "8. Options are shuffled: never name an option by its letter (not 'option "
    "B', 'choice C'); quote its text instead."
)
CARD_RULES: Final = (
    "Hard rules for every card:\n"
    "1. Self-contained: the front makes sense to a student who never saw the "
    "sources; never 'the passage', 'the author', 'the list', 'above'.\n"
    "2. term -> definition or example; formula -> its name and use; problem -> "
    "the full problem on the front, the answer and a short solution on the back.\n"
    "3. Math in LaTeX: $...$ inline; money as \\$60, never a bare $.\n"
    "4. Every slot gets one card; `spec_id` names the slot.\n"
    "5. The front stays under 160 characters and the back under 300: one "
    "answer and the shortest solution, no padding."
)


VISUAL_BLOCKS: Final = (
    "\nVisual blocks (optional): for an item about data (a chart, a table, a "
    "process) put one ```openui block into `stimulus` or `explanation`, never "
    "into `prompt` or the options. The block holds the data the question needs; "
    "the question must still be answerable from it alone. When the student asks "
    "for charts, tables or data, every data item carries one."
)


_TYPE_PHRASES: Final = {
    "single": "4 options, 1 correct",
    "multiple": "4 or 5 options, 2 or 3 correct",
    "true_false": "two options with the ids `true` and `false`",
}


def _slot_line(spec: ItemSpec, cards: bool) -> str:
    kind = "" if cards else f"type={spec.type}, "
    focus = f", focus={spec.focus}" if spec.focus else ""
    source = f", source={spec.source}" if spec.source else ""
    stim = ", needs stimulus" if spec.stimulus else ""
    return (
        f"- {spec.id}: {kind}template={spec.template}, domain={spec.domain}, "
        f"difficulty={spec.difficulty}{source}{focus}{stim}"
    )


def batch_task(
    specs: Sequence[ItemSpec],
    *,
    mode: str,
    cards: bool,
    prompt: str | None,
    avoid: Sequence[str] = (),
    problems: Sequence[str] = (),
    allowed: Sequence[str] = (),
) -> str:
    """The task of one generation batch."""
    what = "flash cards" if cards else "test questions"
    slots = "\n".join(_slot_line(spec, cards) for spec in specs)
    focus = f"\nThe student asked: {prompt}" if prompt else ""
    seen = (
        "\nDo not repeat these existing items:\n"
        + "\n".join(f"- {stem[:120]}" for stem in avoid[-40:])
        if avoid
        else ""
    )
    fixes = (
        "\nEarlier items were rejected for: " + "; ".join(problems[:10])
        if problems
        else ""
    )
    types = (
        ""
        if cards
        else "\nUse only these question types: "
        + ", ".join(
            f"`{name}` = {_TYPE_PHRASES[name]}"
            for name in allowed
            if name in _TYPE_PHRASES
        )
    )
    return (
        f"Write {len(specs)} {what} for a {mode.replace('_', ' ')}, one per "
        f"blueprint slot:\n{slots}\n\n{CARD_RULES if cards else RULES}"
        f"{types}{focus}{seen}{fixes}"
    )


VERIFY_SYSTEM: Final = (
    "You are a strict exam reviewer. You see each item exactly as a student "
    "will, without any source. Answer only with the JSON document."
)


def verify_message(items: Sequence[dict[str, object]], cards: bool) -> str:
    """The checker's task: solve each item without sources and judge it."""
    what = "flash card" if cards else "question"
    return (
        f"For each {what} below decide: self_contained (it can be answered without "
        "any unseen passage, list or table), answer (the option ids you think are "
        "correct; [] for flash cards), single_answer (exactly one defensible key; "
        "for `type` multiple the key is a set of 2 or 3 options, and single_answer "
        "is true when exactly one set of options is defensible; true for flash "
        "cards whose back answers the front) and a short reason.\n"
        + json.dumps(list(items), ensure_ascii=False)
    )
