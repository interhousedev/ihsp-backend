"""Deterministic JSON documents for the notebook Studio, guides and summaries.

Used by ``FakeLlmGateway.complete_json`` (``OPENROUTER__MODE=fake``): every builder
reads the passages found in the prompt (``fake_sources``) and returns a valid document
of the shape in the notebooks spec (§ 3.2.5, § 3.2.6, § 3.4). Without labels the
``refs`` are empty.

The content is demo content and says so: it is made of the real sentences of the
sources (Markdown headings, list markers, ``Front:/Back:`` and ``Question n`` lines
are turned into plain statements first), the titles come from the headings or the
source title, key topics are whole phrases, and no item is ever a filler such as
"Option D" or a cut fragment. A quiz asks for the right-hand side of a formula or
card with the other formulas as (false) distractors, and true/false otherwise.
"""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.ai.domain.errors import AiInvalidOutputError
from app.modules.ai.infrastructure.fake_sources import (
    FakePassage,
    document_passages,
    last_user_text,
    source_titles,
)

Document = dict[str, Any]

EMOJI = "📘"
MAX_CARDS = 10
MAX_QUESTIONS = 10
MAX_ROWS = 10
LETTERS = "abcd"
TOPIC_WORDS = 5  # guides and summaries want 2 to 5 word topics
TOPIC_CHARS = 60
LABEL_CHARS = 60
DEMO = "Demo content"
DEMO_NOTE = (
    "Demo content: this notebook runs without a language model, so the items below "
    "repeat sentences of the sources instead of explaining them."
)
SUMMARY_FILLER = (
    "This demo overview was prepared without a language model for quick revision of "
    "the source and repeats its main statements in short form so that a student can "
    "check the page."
)
# Each is used at most once, so a short source never repeats a sentence.
SUMMARY_FILLERS = (
    SUMMARY_FILLER,
    "The statements keep the wording of the source, so a student can find them on "
    "the page and read the full explanation there.",
    "With a language model switched on, this overview explains the topic in the "
    "student's own language instead of repeating the source.",
)
DEMO_OVERVIEW = "Demo overview without a language model."
REPORT_INTRO = "Statements of this part of the sources, as the sources put them."
# Generic study topics that fill a short list (2 to 5 words each, never a fragment).
GENERIC_TOPICS = (
    "Key facts",
    "Worked examples",
    "Self-check questions",
    "Terms to remember",
    "Typical mistakes",
    "Main idea",
    "Short summary",
    "Study plan",
    "Open questions",
    "Further reading",
)
GENERIC_QUESTIONS = (
    "What is the main idea of this source?",
    "Which facts should I remember from this source?",
    "Which examples does this source give?",
    "Which terms does this source define?",
    "What could a test ask about this source?",
    "How does this source connect to the other sources?",
)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[^\W_][\w'ʻʼ’-]*")
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_LIST_MARK = re.compile(r"^(?:[-*+]|\d+[.)])[ \t]+")
_SKIPPED_LINE = re.compile(
    r"^(?:Test: \d+ questions?\.|Flash cards: \d+ cards?\.|Card \d+|Options?:.*|"
    r"Items \(in random order\):.*|Left:.*|Right \(in random order\):.*|Rows:.*|"
    r"Columns:.*|Variables:.*|Language:.*|Key topics:.*|Questions:.*)$"
)
_QUESTION = re.compile(r"^Question \d+ \([^)]*\): (.+)$")
_CARD_FRONT = re.compile(r"^(?:Front|Q): (.+)$")
_CARD_BACK = re.compile(r"^(?:Back|A): (.+)$")
_SUMMARY_LINE = re.compile(r"^Summary: (.+)$")
_MATH = re.compile(r"\$+")
_INLINE = re.compile(r"[*_`]{1,3}")
_GUIDE_BLOCK = re.compile(
    r'<guide\b[^>]*\btitle="([^"]*)"[^>]*>(.*?)</guide>', re.DOTALL
)
_LIST_ITEM = re.compile(r"^Key topics: (.+)$|^Questions: (.+)$")


# - - - Text helpers - - -


def sentences(text: str) -> list[str]:
    """Split text into sentences after collapsing whitespace; never empty."""
    flat = " ".join(text.split())
    parts = [part for part in _SENTENCE_END.split(flat) if part]
    return parts or [flat]


def first_sentence(text: str) -> str:
    """Return the first statement of a passage (plain, no Markdown)."""
    found = statements(text)
    return found[0] if found else sentences(text)[0]


def head_words(text: str, count: int) -> str:
    """Return the first ``count`` words without punctuation around them."""
    return " ".join(_WORD.findall(text)[:count])


def clip(text: str, limit: int) -> str:
    """Cut text to ``limit`` characters."""
    return text[:limit].rstrip()


def clip_words(text: str, limit: int) -> str:
    """Return the first ``limit`` words of a text."""
    return " ".join(text.split()[:limit])


def phrase(text: str, limit: int = LABEL_CHARS) -> str:
    """A whole text when it fits, else its first words with an ellipsis."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[: limit - 1]
    return cut[: cut.rfind(" ")].rstrip(",;:.-") + "…" if " " in cut else cut + "…"


def plain(text: str) -> str:
    """One line without Markdown emphasis, ``$`` math fences or list markers."""
    flat = " ".join(_INLINE.sub("", _MATH.sub("", text)).split())
    return _LIST_MARK.sub("", flat).strip()


def heading_of(text: str) -> str | None:
    """The first Markdown heading of a passage, as plain text, or None."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _HEADING.match(stripped)
        return plain(match.group(1)).rstrip(":.!") if match else None
    return None


def labels_of(text: str) -> list[str]:
    """Short label lines such as ``Rules to remember:`` (without the colon)."""
    found: list[str] = []
    for raw in text.splitlines():
        line = plain(raw.strip())
        if line.endswith(":") and 1 <= len(line.split()) <= TOPIC_WORDS + 1:
            found.append(line.rstrip(":"))
    return found


def statements(text: str) -> list[str]:
    """The sentences of a passage, in order, as plain statements.

    Headings, ``Card n``/``Options:`` lines and the like are dropped; a flash card
    becomes ``front — back``; a test question keeps its prompt; a guide's
    ``Summary:`` line gives its sentences. Statements shorter than two words are
    dropped unless they hold a formula (``=``).
    """
    found: list[str] = []
    front: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _HEADING.match(line) or _SKIPPED_LINE.match(line):
            continue
        if (card := _CARD_FRONT.match(line)) is not None:
            front = plain(card.group(1))
            continue
        if (back := _CARD_BACK.match(line)) is not None:
            if front:
                found.append(f"{front} — {plain(back.group(1))}")
            front = None
            continue
        if (asked := _QUESTION.match(line)) is not None:
            prompt = plain(asked.group(1))
            found.append(prompt if prompt.endswith("?") else prompt.rstrip(".!") + "?")
            continue
        summary = _SUMMARY_LINE.match(line)
        body = plain(summary.group(1) if summary else line)
        found.extend(s for s in sentences(body) if _is_statement(s))
    return unique(found)


def _is_statement(sentence: str) -> bool:
    """Two words or a formula, and not a label such as ``Rules to remember:``."""
    if sentence.endswith(":"):
        return False
    return len(sentence.split()) >= 2 or "=" in sentence


@dataclass(frozen=True, slots=True)
class Statement:
    """One plain statement and the passage it comes from."""

    text: str
    passage: FakePassage

    @property
    def sides(self) -> tuple[str, str] | None:
        """``(left, right)`` of a card (``front — back``) or a formula (``x = y``)."""
        if " — " in self.text:
            left, right = self.text.split(" — ", 1)
        elif self.text.count("=") == 1 and len(self.text.split()) < 10:
            left, right = self.text.split("=", 1)
        else:
            return None
        left, right = left.strip(), right.strip()
        return (left, right) if left and right else None

    @property
    def is_question(self) -> bool:
        """A question of a test (never an answer or a card)."""
        return self.text.endswith("?")


def teachable(found: Sequence[Statement]) -> list[Statement]:
    """Statements that can be a card or an answer: not questions of a test."""
    kept = [s for s in found if not s.is_question]
    return kept or list(found)


def all_statements(passages: Sequence[FakePassage]) -> list[Statement]:
    """Every statement of every passage, in order, without repeats."""
    seen: set[str] = set()
    found: list[Statement] = []
    for passage in passages:
        for text in statements(passage.text):
            if text.casefold() not in seen:
                seen.add(text.casefold())
                found.append(Statement(text, passage))
    if not found:
        found.append(Statement(first_sentence(passages[0].text), passages[0]))
    return found


def topic(text: str) -> str:
    """Return a short label for a passage: its heading, else its opening words."""
    label = clip_words(heading_of(text) or first_sentence(text), TOPIC_WORDS)
    label = label.rstrip(",;:.")
    if len(label.split()) < 2:
        label = f"{label} topic".strip() if label else "Main topic"
    return clip(label, TOPIC_CHARS)


def title_of(passages: Sequence[FakePassage], titles: Sequence[str] = ()) -> str:
    """The title of a document: the first heading, else the source title."""
    heading = heading_of(passages[0].text)
    if heading:
        return phrase(heading.rstrip("?"), TOPIC_CHARS)
    if titles and titles[0]:
        return phrase(titles[0], TOPIC_CHARS)
    return topic(passages[0].text)


def cited(passage: FakePassage) -> str:
    """Return the first statement followed by its ``[[label]]`` marker."""
    sentence = first_sentence(passage.text)
    return f"{sentence} [[{passage.label}]]" if passage.label else sentence


def unique(candidates: Sequence[str]) -> list[str]:
    """Drop repeats (case-insensitive), keeping the order."""
    seen: set[str] = set()
    result: list[str] = []
    for text in candidates:
        if text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return result


def cycle(passages: Sequence[FakePassage], index: int) -> FakePassage:
    """Return the passage at ``index``, wrapping around."""
    return passages[index % len(passages)]


def _pad(found: list[str], low: int, high: int, generic: Sequence[str]) -> list[str]:
    """``low`` to ``high`` items: the found ones, then generic ones."""
    result = unique(found)[:high]
    for item in generic:
        if len(result) >= low:
            break
        if item.casefold() not in {r.casefold() for r in result}:
            result.append(item)
    return result


def _word_count_ok(text: str) -> bool:
    return 2 <= len(text.split()) <= TOPIC_WORDS


def key_phrases(
    passages: Sequence[FakePassage], titles: Sequence[str] = ()
) -> list[str]:
    """Whole phrases a student would call the topics of the passages.

    Headings, label lines (``Rules to remember``), cards and formulas as ``x = y``
    and short whole statements; each 2 to 5 words, never a cut fragment.
    """
    found: list[str] = []
    for passage in passages:
        heading = heading_of(passage.text)
        if heading:
            found.append(heading.rstrip("?"))
        found.extend(labels_of(passage.text))
    for title in titles:
        found.append(title)
    for statement in all_statements(passages):
        sides = statement.sides
        if sides is not None:
            found.append(f"{sides[0]} = {sides[1]}")
        elif not statement.is_question:
            found.append(statement.text.rstrip(".!"))
    return [p for p in unique(found) if _word_count_ok(p)]


def _sentence(text: str) -> str:
    """A statement as a sentence: a full stop after a formula or a card."""
    return text if text[-1] in ".!?" else f"{text}."


def summary_text(passages: Sequence[FakePassage], low: int, high: int) -> str:
    """Return ``low`` to ``high`` words made from the statements (padded if short).

    Prose and formulas come first; a source that holds only test questions is
    described by its questions.
    """
    found = all_statements(passages)
    words: list[str] = []
    for statement in [s for s in found if not s.is_question]:
        words.extend(_sentence(statement.text).split())
        if len(words) >= low:
            break
    asked = [s.text for s in found if s.is_question]
    if len(words) < low and asked:
        words.extend(f"The source asks: {' '.join(asked)}".split())
    for filler in SUMMARY_FILLERS:  # each once: a repeated sentence reads as a glitch
        if len(words) >= low:
            break
        words.extend(filler.split())
    return " ".join(words[:high])


def topics(
    passages: Sequence[FakePassage], low: int, high: int, titles: Sequence[str] = ()
) -> list[str]:
    """``low`` to ``high`` distinct 2 to 5 word topics; generic ones fill the list."""
    return _pad(key_phrases(passages, titles), low, high, GENERIC_TOPICS)


def _question_of(statement: Statement) -> str | None:
    """A natural question a student could ask about one statement."""
    if statement.is_question:
        return statement.text
    sides = statement.sides
    if sides is not None:
        return f"What does {sides[0]} equal?"
    body = statement.text.rstrip(".!")
    if len(body.split()) > 14:
        return None
    return f"How would you explain that {body[0].lower()}{body[1:]}?"


def questions(
    passages: Sequence[FakePassage], count: int, titles: Sequence[str] = ()
) -> list[str]:
    """Return ``count`` natural questions a student could ask about the passages."""
    found: list[str] = []
    for passage in passages:
        heading = heading_of(passage.text)
        if heading and heading.endswith("?"):
            found.append(heading)
        found.extend(
            f"What are the {label.lower()}?" for label in labels_of(passage.text)
        )
    found.extend(q for s in all_statements(passages) if (q := _question_of(s)))
    return _pad(found, count, count, GENERIC_QUESTIONS)


# - - - Guides and summaries - - -


def build_guide(passages: Sequence[FakePassage], _: str) -> Document:
    """The source guide (§ 3.2.5)."""
    return {
        "summary": summary_text(passages, 70, 100),
        "key_topics": topics(passages, 5, 8),
        "questions": questions(passages, 3),
    }


def build_guide_document(
    passages: Sequence[FakePassage], messages: Sequence[dict[str, Any]]
) -> Document:
    """The source guide, with the ``<source title>`` as a topic of last resort."""
    titles = source_titles(messages)
    return {
        "summary": summary_text(passages, 70, 100),
        "key_topics": topics(passages, 5, 8, titles),
        "questions": questions(passages, 3, titles),
    }


@dataclass(frozen=True, slots=True)
class _Guide:
    """One ``<guide>`` of the summary prompt, parsed."""

    title: str
    summary: str
    key_topics: list[str]
    questions: list[str]


def _parse_guides(text: str) -> list[_Guide]:
    guides: list[_Guide] = []
    for title, body in _GUIDE_BLOCK.findall(text):
        summary, key_topics, asked = "", [], []
        for raw in body.strip().splitlines():
            line = raw.strip()
            if (match := _SUMMARY_LINE.match(line)) is not None:
                summary = plain(match.group(1))
            elif line.startswith("Key topics: "):
                key_topics = [t.strip() for t in line[12:].split(";") if t.strip()]
            elif line.startswith("Questions: "):
                asked = [q.strip() for q in line[11:].split(" | ") if q.strip()]
        guides.append(_Guide(" ".join(title.split()), summary, key_topics, asked))
    return guides


def _bold_summary(words: list[str]) -> str:
    bold = " ".join(words[:3])
    return f"**{bold}** {' '.join(words[3:])}"


def build_summary(passages: Sequence[FakePassage], _: str) -> Document:
    """The notebook title, emoji and overview (§ 3.2.6) from labelled passages."""
    words = summary_text(passages, 90, 130).split()
    return {
        "title": title_of(passages),
        "emoji": EMOJI,
        "summary": _bold_summary(words),
        "key_topics": topics(passages, 6, 10),
        "suggested_questions": questions(passages, 4),
    }


def build_summary_document(
    passages: Sequence[FakePassage], messages: Sequence[dict[str, Any]]
) -> Document:
    """The notebook overview from the ``<guides>`` of its sources (§ 3.2.6)."""
    guides = _parse_guides(last_user_text(messages))
    if not guides:
        return build_summary(passages, "")
    words: list[str] = []
    for guide in guides:
        words.extend(_sentence(guide.summary).split() if guide.summary else [])
        if len(words) >= 90:
            break
    for filler in SUMMARY_FILLERS:  # each once: a repeated sentence reads as a glitch
        if len(words) >= 90:
            break
        words.extend(filler.split())
    found_topics = [t for g in guides for t in g.key_topics if _word_count_ok(t)]
    asked = [q for g in guides for q in g.questions]
    return {
        "title": phrase(guides[0].title, TOPIC_CHARS),
        "emoji": EMOJI,
        "summary": f"**{DEMO_OVERVIEW}** {' '.join(words[:124])}",
        "key_topics": _pad(found_topics, 6, 10, GENERIC_TOPICS),
        "suggested_questions": _pad(asked, 4, 6, GENERIC_QUESTIONS),
    }


# - - - Reports and maps - - -


def build_report(passages: Sequence[FakePassage], _: str) -> Document:
    """A conspect with a main idea and three cited sections (§ 3.4.1)."""
    title = title_of(passages)
    lines = [
        f"# {title}",
        "",
        f"> {DEMO_NOTE}",
        "",
        "## Main idea",
        cited(passages[0]),
        "",
    ]
    chosen = [cycle(passages, n) for n in range(max(len(passages), 3))][:12]
    for number in range(3):
        group = chosen[number::3]
        lines += [f"## {number + 1}. {topic(group[0].text)}", REPORT_INTRO, ""]
        for passage in group:
            marker = f" [[{passage.label}]]" if passage.label else ""
            lines += [f"- {s}{marker}" for s in statements(passage.text)[:3]]
        lines.append("")
    return {"title": f"{title}: demo conspect", "markdown": "\n".join(lines).strip()}


LABEL_WORDS = 6  # a mind map label is a noun phrase of at most 6 words (§ 3.4.2)
_CLAUSE_END = re.compile(r"[,;:]| — ")


def short_label(text: str) -> str:
    """A whole phrase of at most 6 words: the text, its first clause, or a cut + "…"."""
    flat = " ".join(text.split()).rstrip(".!")
    if len(flat.split()) <= LABEL_WORDS:
        return flat
    head = _CLAUSE_END.split(flat, 1)[0].strip()
    if 2 <= len(head.split()) <= LABEL_WORDS:
        return head
    return " ".join(flat.split()[:LABEL_WORDS]).rstrip(",;:.-") + "…"


def _short_first(texts: Sequence[str]) -> list[str]:
    """Whole phrases that fit a label come before the ones that must be cut."""
    return sorted(texts, key=lambda t: len(t.split()) > LABEL_WORDS)


def _concept_label(passage: FakePassage, taken: set[str]) -> str:
    """A level-1 label: the heading, a label line, else a whole short statement."""
    candidates = [heading_of(passage.text) or "", *labels_of(passage.text)]
    candidates += _short_first([s.text for s in all_statements([passage])])
    for candidate in candidates:
        label = short_label(candidate.rstrip("?")) if candidate else ""
        if label and not any(_same_phrase(label, done) for done in taken):
            return label
    return short_label(first_sentence(passage.text))


def build_mind_map(passages: Sequence[FakePassage], _: str) -> Document:
    """A root, up to four main concepts and their details, whole phrases (§ 3.4.2)."""
    root = passages[0]
    title = title_of(passages)
    nodes = [_node(1, None, title, root, DEMO_NOTE)]
    taken = {title.casefold()}
    main = passages[:4]
    for index, passage in enumerate(main):
        label = _concept_label(passage, taken)
        taken.add(label.casefold())
        nodes.append(_node(2 + index, 1, label, passage, first_sentence(passage.text)))
    for index, passage in enumerate(main):
        detail = _detail(passage.text, nodes[1 + index]["label"])
        nodes.append(
            _node(
                2 + len(main) + index, 2 + index, short_label(detail), passage, detail
            )
        )
    return {"title": f"{title}: demo mind map", "nodes": nodes}


def _same_phrase(first: str, second: str) -> bool:
    return first.rstrip("?.!…").casefold() == second.rstrip("?.!…").casefold()


def _detail(text: str, parent_label: str) -> str:
    """A statement other than the parent's label (short ones first), else the first."""
    parts = statements(text)
    for part in _short_first(parts):
        if not _same_phrase(short_label(part), parent_label):
            return part
    return parts[0] if parts else first_sentence(text)


def _node(
    number: int, parent: int | None, label: str, passage: FakePassage, note: str
) -> Document:
    return {
        "id": f"n{number}",
        "parent_id": None if parent is None else f"n{parent}",
        "label": clip(label, TOPIC_CHARS),
        "note": clip(note, 200),
        "refs": passage.refs,
    }


# - - - Cards, quiz and table - - -


def _card_sides(statement: str) -> tuple[str, str]:
    """A flash card from a statement: ``front — back`` as is, else a cloze.

    A short formula asks for its right-hand side (``(c)' = ?``); a sentence asks to
    finish its first half.
    """
    sides = Statement(statement, FakePassage("", "")).sides
    if sides is not None:
        front, back = sides
        return (front, back) if " — " in statement else (f"{front} = ?", statement)
    words = statement.split()
    if len(words) < 4:
        return f"What does the source say here: {statement}", statement
    half = max(2, len(words) // 2)
    return f"Finish the statement: {' '.join(words[:half])} …", statement


def build_flashcards(passages: Sequence[FakePassage], _: str) -> Document:
    """Cards from the statements of the sources, up to ten (§ 3.4.3)."""
    chosen = teachable(all_statements(passages))[:MAX_CARDS]
    cards: list[Document] = []
    seen: set[str] = set()
    for statement in chosen:
        front, back = _card_sides(statement.text)
        if front.casefold() in seen:
            front = f"{front} ({len(cards) + 1})"
        seen.add(front.casefold())
        cards.append(
            {
                "id": f"c{len(cards) + 1}",
                "front": clip(front, 160),
                "back": clip(back, 300),
                "hint": f"{DEMO}: re-read «{topic(statement.passage.text)}».",
                "topic": clip(topic(statement.passage.text), 40),
                "refs": statement.passage.refs,
            }
        )
    return {"title": f"{title_of(passages)}: demo cards", "cards": cards}


def _question(
    number: int,
    kind: str,
    prompt: str,
    options: list[tuple[str, str]],
    correct: str | list[str],
    explanation: str,
    statement: Statement,
) -> Document:
    return {
        "id": f"q{number}",
        "type": kind,
        "prompt": clip(prompt, 400),
        "options": [{"id": i, "text": clip(t, 200)} for i, t in options],
        "correct": [correct] if isinstance(correct, str) else correct,
        "explanation": explanation,
        "hint": f"{DEMO}: re-read «{topic(statement.passage.text)}».",
        "difficulty": "easy",
        "topic": clip(topic(statement.passage.text), 40),
        "refs": statement.passage.refs,
    }


def _pairs(found: Sequence[Statement]) -> list[tuple[str, str, Statement]]:
    """``(left, right, statement)`` of every card or formula, one per left side."""
    pairs: list[tuple[str, str, Statement]] = []
    seen: set[str] = set()
    for statement in found:
        sides = statement.sides
        if sides is None or sides[0].casefold() in seen:
            continue
        seen.add(sides[0].casefold())
        pairs.append((sides[0], sides[1], statement))
    return pairs


def _choice_questions(pairs: Sequence[tuple[str, str, Statement]]) -> list[Document]:
    """``What does X equal?`` with the other right-hand sides as false options."""
    items: list[Document] = []
    for index, (left, right, statement) in enumerate(pairs):
        wrong = unique(
            [r for other_left, r, _ in pairs if r.casefold() != right.casefold()]
        )[: len(LETTERS) - 1]
        if not wrong:
            continue
        slot = index % (len(wrong) + 1)
        texts = [*wrong[:slot], right, *wrong[slot:]]
        items.append(
            _question(
                0,
                "single",
                f"What does {left} equal?",
                [(LETTERS[n], t) for n, t in enumerate(texts)],
                LETTERS[slot],
                f"{DEMO}: the source says «{left} = {right}»; the other options "
                "belong to other formulas or cards.",
                statement,
            )
        )
    return items


def _true_false_questions(
    found: Sequence[Statement], pairs: Sequence[tuple[str, str, Statement]]
) -> list[Document]:
    """True statements as written, and false ones made of a mismatched pair."""
    options = [("true", "True"), ("false", "False")]
    items: list[Document] = []
    prose = [s for s in found if s.sides is None]
    for index, statement in enumerate(prose):
        items.append(
            _question(
                0,
                "true_false",
                f"True or false: {statement.text}",
                options,
                "true",
                f"{DEMO}: the source says exactly this.",
                statement,
            )
        )
        if index < len(pairs) and len(pairs) > 1:
            left, right, origin = pairs[index]
            wrong = next(r for _, r, _ in pairs if r.casefold() != right.casefold())
            items.append(
                _question(
                    0,
                    "true_false",
                    f"True or false: {left} = {wrong}",
                    options,
                    "false",
                    f"{DEMO}: the source says «{left} = {right}», not «{wrong}».",
                    origin,
                )
            )
    return items


_QUIZ_TYPES = ("single", "multiple", "true_false")


def _requested_types(task: str) -> list[str]:
    """The question types the task restricts the quiz to (all of them by default)."""
    found = re.findall(r"`(single|multiple|true_false)` =", task)
    return [kind for kind in _QUIZ_TYPES if kind in found] or list(_QUIZ_TYPES)


def _by_passage(found: Sequence[Statement]) -> list[list[Statement]]:
    """The statements grouped by their passage, in order."""
    groups: dict[str, list[Statement]] = {}
    for statement in found:
        groups.setdefault(statement.passage.text, []).append(statement)
    return list(groups.values())


def _passage_questions(
    found: Sequence[Statement], kinds: Sequence[str]
) -> list[Document]:
    """``Which statement comes from this passage?`` over sources without formulas.

    The right options are statements of the passage, the wrong ones are statements of
    other passages, so every option is checkable against the sources.
    """
    groups = _by_passage(found)
    items: list[Document] = []
    for index, group in enumerate(groups):
        outside = unique([g[0].text for n, g in enumerate(groups) if n != index and g])
        own = unique([s.text for s in group])
        about = topic(group[0].passage.text)
        explanation = (
            f"{DEMO}: the source says this in «{about}»; the other options come "
            "from other passages."
        )
        if "single" in kinds and outside:
            texts = [own[0], *outside[: len(LETTERS) - 1]]
            items.append(
                _question(
                    0,
                    "single",
                    f"Which statement comes from the passage «{about}»?",
                    [(LETTERS[n], t) for n, t in enumerate(texts)],
                    LETTERS[0],
                    explanation,
                    group[0],
                )
            )
        if "multiple" in kinds and len(own) >= 2 and outside:
            texts = [*own[:2], *outside[:2]]
            items.append(
                _question(
                    0,
                    "multiple",
                    f"Which statements come from the passage «{about}»?",
                    [(LETTERS[n], t) for n, t in enumerate(texts)],
                    [LETTERS[0], LETTERS[1]],
                    explanation,
                    group[0],
                )
            )
    return items


def build_quiz(passages: Sequence[FakePassage], task: str) -> Document:
    """Single choice over formulas and cards, true/false over sentences (§ 3.4.4).

    Every single choice question has exactly one true option: the right-hand side of
    its own formula or card; the distractors are the right-hand sides of the others.
    Sentences become true/false questions, mixed with false formula statements. Only
    the requested question types are made; without formulas, single and multiple
    choice ask which statements come from a passage.
    """
    kinds = _requested_types(task)
    found = teachable(all_statements(passages))
    pairs = _pairs(found)
    items: list[Document] = []
    if "single" in kinds:
        items += _choice_questions(pairs)
    if "true_false" in kinds:
        items += _true_false_questions(found, pairs)
    if not items:
        items = _passage_questions(found, kinds)
    if not items:
        items = [
            _question(
                0,
                "true_false",
                f"True or false: {found[0].text}",
                [("true", "True"), ("false", "False")],
                "true",
                f"{DEMO}: the source says exactly this.",
                found[0],
            )
        ]
    numbered = [
        {**item, "id": f"q{n}"} for n, item in enumerate(items[:MAX_QUESTIONS], 1)
    ]
    return {"title": f"{title_of(passages)}: demo quiz", "questions": numbered}


def build_data_table(passages: Sequence[FakePassage], _: str) -> Document:
    """A term and definition table, one row per statement (§ 3.4.5)."""
    rows = []
    for statement in teachable(all_statements(passages))[:MAX_ROWS]:
        term, definition = _card_sides(statement.text)
        if term.startswith("Finish the statement: "):
            term = clip_words(statement.text, 4)
        rows.append(
            {
                "cells": {"term": clip(term, 120), "definition": clip(definition, 120)},
                "refs": statement.passage.refs,
            }
        )
    return {
        "title": f"{title_of(passages)}: demo table",
        "columns": [
            {"key": "term", "label": "Term", "type": "text"},
            {"key": "definition", "label": "Definition", "type": "text"},
        ],
        "rows": rows,
    }


# - - - Slides and infographic - - -


def _bullets(text: str, limit: int = 3) -> list[str]:
    found = [clip_words(s, 12) for s in statements(text)[:limit]]
    return found or [clip_words(first_sentence(text), 12)]


def _slide_notes(text: str) -> str:
    opening = clip(first_sentence(text), 180)
    return f"{DEMO}. Explain this slide in your own words: {opening}"


def _both_refs(first: FakePassage, second: FakePassage) -> list[str]:
    return unique(first.refs + second.refs)


def build_slides(passages: Sequence[FakePassage], _: str) -> Document:
    """Title, agenda, four bullet slides, two columns and a summary (§ 3.4.6)."""
    title = title_of(passages)
    content: list[Document] = []
    for number in range(4):
        passage = cycle(passages, number)
        content.append(
            {
                "layout": "bullets",
                "title": topic(passage.text),
                "bullets": _bullets(passage.text),
                "notes": _slide_notes(passage.text),
                "visual_hint": f"Simple diagram of {topic(passage.text).lower()}",
                "refs": passage.refs,
            }
        )
    left, right = cycle(passages, 0), cycle(passages, 1)
    content.append(
        {
            "layout": "two_columns",
            "title": "Compare",
            "notes": _slide_notes(left.text),
            "left": {"heading": topic(left.text), "bullets": _bullets(left.text, 2)},
            "right": {"heading": topic(right.text), "bullets": _bullets(right.text, 2)},
            "refs": _both_refs(left, right),
        }
    )
    agenda = unique([slide["title"] for slide in content])
    slides: list[Document] = [
        {
            "layout": "title",
            "title": title,
            "bullets": [],
            "notes": f"{DEMO}. Welcome the class. Introduce the topic of this deck.",
            "refs": [],
        },
        {
            "layout": "agenda",
            "title": "Agenda",
            "bullets": agenda if len(agenda) >= 2 else [*agenda, "Summary"],
            "notes": "Show the plan of the talk.",
            "refs": [],
        },
        *content,
        {
            "layout": "summary",
            "title": "Summary",
            "bullets": [clip_words(first_sentence(p.text), 12) for p in passages[:4]],
            "notes": "Recap the main points. Ask the class one question.",
            "refs": _both_refs(cycle(passages, 0), cycle(passages, 1)),
        },
    ]
    numbered = [{"id": f"s{n}", **slide} for n, slide in enumerate(slides, start=1)]
    return {
        "title": title,
        "subtitle": "Demo deck (no language model)",
        "slides": numbered,
    }


def build_slides_revise(_: Sequence[FakePassage], task: str) -> Document:
    """Return the slides named in ``changes`` with ``" (revised)"`` after the title."""
    request = _embedded_request(task)
    named = {
        change.get("slide_id")
        for change in request.get("changes") or []
        if isinstance(change, dict)
    }
    revised = [
        {**slide, "title": f"{slide.get('title', '')} (revised)"}
        for slide in request.get("slides") or []
        if isinstance(slide, dict) and slide.get("id") in named
    ]
    return {"slides": revised}


def _embedded_request(text: str) -> Document:
    """Find the ``{"slides": [...], "changes": [...]}`` object inside a message."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            value = None
        if isinstance(value, dict) and "slides" in value and "changes" in value:
            return value
        start = text.find("{", start + 1)
    return {}


def _item(passage: FakePassage, head: str | None = None) -> Document:
    label = head if head is not None else clip_words(topic(passage.text), 2)
    return {
        "head": clip(label, 40),
        "body": clip_words(first_sentence(passage.text), 18),
    }


def build_infographic(passages: Sequence[FakePassage], _: str) -> Document:
    """Six blocks of different types (§ 3.4.7)."""
    first, second, last = cycle(passages, 0), cycle(passages, 1), cycle(passages, -1)
    steps = [cycle(passages, n) for n in range(3)]
    points = [cycle(passages, n) for n in range(4)]
    blocks: list[Document] = [
        {"type": "stat", "title": "", "items": [_item(first)], "refs": first.refs},
        {
            "type": "steps",
            "title": "Process",
            "items": [_item(p) for p in steps],
            "refs": unique([r for p in steps for r in p.refs]),
        },
        {
            "type": "comparison",
            "title": "Two views",
            "columns": [
                {"title": topic(p.text), "points": _bullets(p.text, 2)}
                for p in (first, second)
            ],
            "refs": _both_refs(first, second),
        },
        {
            "type": "list",
            "title": "Key points",
            "items": [_item(p) for p in points],
            "refs": unique([r for p in points for r in p.refs]),
        },
        {
            "type": "timeline",
            "title": "Sequence",
            "items": [_item(p, f"Step {n}") for n, p in enumerate(steps, start=1)],
            "refs": unique([r for p in steps for r in p.refs]),
        },
        {
            "type": "callout",
            "title": "Remember",
            "items": [_item(last, "Key takeaway")],
            "refs": last.refs,
        },
    ]
    return {
        "title": f"{title_of(passages)} at a glance",
        "subtitle": "Demo infographic (no language model)",
        "footer": "Prepared from the notebook sources",
        "blocks": blocks,
    }


_SOURCE_KEY = re.compile(r'<source key="(s\d+)" title="([^"]*)"')
LABEL_EMOJIS = ("📘", "🧪", "🌍", "🧮")


_TOPIC_WORD = {"ru": "Тема", "uz": "Mavzu", "en": "Topic"}


def label_language(messages: Sequence[dict[str, Any]]) -> str:
    """The language the label prompt asks for (``Write the label names in Russian``)."""
    for message in messages:
        content = message.get("content")
        if message.get("role") == "system" and isinstance(content, str):
            if "label names in Russian" in content:
                return "ru"
            if "label names in Uzbek" in content:
                return "uz"
    return "en"


def build_labels(
    passages: Sequence[FakePassage], text: str, language: str = "en"
) -> Document:
    """Up to 3 topic labels over the ``<source key=... title=...>`` tags.

    The names are in ``language``.
    """
    word = _TOPIC_WORD.get(language, "Topic")
    sources = _SOURCE_KEY.findall(text)
    count = max(1, min(3, len(sources)))
    labels = [
        {"key": f"l{n + 1}", "name": f"{word} {n + 1}", "emoji": LABEL_EMOJIS[n]}
        for n in range(count)
    ]
    assignments = [
        {"source": key, "labels": [f"l{n % count + 1}"]}
        for n, (key, _) in enumerate(sources)
    ]
    return {"labels": labels, "assignments": assignments}


def build_slides_plan(passages: Sequence[FakePassage], text: str) -> Document:
    """A presentation plan (PLAN): the slide titles of the fake deck with bullets."""
    deck = build_slides(passages, text)
    slides = [
        {
            "title": slide["title"],
            "bullets": list(slide.get("bullets") or [])[:5]
            or [topic(cycle(passages, n).text)],
        }
        for n, slide in enumerate(deck["slides"])
    ]
    return {"title": deck.get("title") or title_of(passages), "slides": slides}


Builder = Callable[[Sequence[FakePassage], str], Document]

BUILDERS: dict[str, Builder] = {
    "nb_slides_plan": build_slides_plan,
    "nb_guide": build_guide,
    "nb_summary": build_summary,
    "nb_report": build_report,
    "nb_mind_map": build_mind_map,
    "nb_flashcards": build_flashcards,
    "nb_quiz": build_quiz,
    "nb_data_table": build_data_table,
    "nb_slides": build_slides,
    "nb_slides_revise": build_slides_revise,
    "nb_infographic": build_infographic,
    "nb_labels": build_labels,
}


def build_document(schema_name: str, messages: Sequence[dict[str, Any]]) -> Document:
    """Return the fake document for ``schema_name``.

    Raises:
        AiInvalidOutputError: The schema name is not a notebook schema.
    """
    builder = BUILDERS.get(schema_name)
    if builder is None:
        raise AiInvalidOutputError(support_details=f"unknown schema {schema_name}")
    passages = document_passages(messages)
    if builder is build_labels:
        return build_labels(
            passages, last_user_text(messages), label_language(messages)
        )
    if builder is build_guide:
        return build_guide_document(passages, messages)
    if builder is build_summary:
        return build_summary_document(passages, messages)
    return builder(passages, last_user_text(messages))
