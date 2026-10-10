"""Deterministic JSON documents for the notebook Studio, guides and summaries.

Used by ``FakeLlmGateway.complete_json`` (``OPENROUTER__MODE=fake``): every builder
reads the passages found in the prompt (``fake_sources``) and returns a valid document
of the shape in the notebooks spec (§ 3.2.5, § 3.2.6, § 3.4). Without labels the
``refs`` are empty.

The content is demo content and says so: it is made of the real sentences of the
sources (Markdown headings, list markers, ``Front:/Back:`` and ``Question n`` lines
are turned into plain statements first), the titles come from the headings, and no
item is ever a filler such as "Option D". A quiz with too few statements for
distractors asks true/false questions instead.
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
)

Document = dict[str, Any]

EMOJI = "📘"
MAX_CARDS = 10
MAX_QUESTIONS = 5
MAX_ROWS = 10
LETTERS = "abcd"
TOPIC_WORDS = 5  # guides and summaries want 2 to 5 word topics
TOPIC_CHARS = 60
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
REPORT_INTRO = "Statements of this part of the sources, as the sources put them."

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[^\W_][\w'ʻʼ’-]*")
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_LIST_MARK = re.compile(r"^(?:[-*+]|\d+[.)])[ \t]+")
_SKIPPED_LINE = re.compile(
    r"^(?:Test: \d+ questions?\.|Flash cards: \d+ cards?\.|Card \d+|Options?:.*|"
    r"Items \(in random order\):.*|Left:.*|Right \(in random order\):.*|Rows:.*|"
    r"Columns:.*|Variables:.*|Language:.*)$"
)
_QUESTION = re.compile(r"^Question \d+ \([^)]*\): (.+)$")
_CARD_FRONT = re.compile(r"^(?:Front|Q): (.+)$")
_CARD_BACK = re.compile(r"^(?:Back|A): (.+)$")
_MATH = re.compile(r"\$+")
_INLINE = re.compile(r"[*_`]{1,3}")


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
        return plain(match.group(1)).rstrip("?:.!") if match else None
    return None


def statements(text: str) -> list[str]:
    """The sentences of a passage, in order, as plain statements.

    Headings, ``Card n``/``Options:`` lines and the like are dropped; a flash card
    becomes ``front — back``; a test question keeps its prompt. Statements shorter
    than two words are dropped unless they hold a formula (``=``).
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
        question = _QUESTION.match(line)
        body = plain(question.group(1) if question else line)
        found.extend(s for s in sentences(body) if _is_statement(s))
    return unique(found)


def _is_statement(sentence: str) -> bool:
    """Two words or a formula, and not a label such as ``Rules to remember:``."""
    if sentence.endswith(":"):
        return False
    return len(sentence.split()) >= 2 or "=" in sentence


def teachable(found: Sequence["Statement"]) -> list["Statement"]:
    """Statements that can be a card or an answer: not questions of a test."""
    kept = [s for s in found if not s.text.endswith("?")]
    return kept or list(found)


def topic(text: str) -> str:
    """Return a short label for a passage: its heading, else its opening words."""
    label = clip_words(heading_of(text) or first_sentence(text), TOPIC_WORDS)
    label = label.rstrip(",;:.")
    if len(label.split()) < 2:
        label = f"{label} topic".strip() if label else "Main topic"
    return clip(label, TOPIC_CHARS)


def title_of(passages: Sequence[FakePassage]) -> str:
    """Return the title of a document: the topic of the first passage."""
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


@dataclass(frozen=True, slots=True)
class Statement:
    """One plain statement and the passage it comes from."""

    text: str
    passage: FakePassage


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


def summary_text(passages: Sequence[FakePassage], low: int, high: int) -> str:
    """Return ``low`` to ``high`` words made from the statements (padded if short)."""
    words: list[str] = []
    for statement in all_statements(passages):
        words.extend(statement.text.split())
        if len(words) >= low:
            break
    while len(words) < low:
        words.extend(SUMMARY_FILLER.split())
    return " ".join(words[:high])


def topics(passages: Sequence[FakePassage], low: int, high: int) -> list[str]:
    """Return ``low`` to ``high`` distinct 2 to 6 word topics."""
    found = unique([topic(p.text) for p in passages])[:high]
    while len(found) < low:
        found.append(f"Key topic {len(found) + 1}")
    return found


def questions(passages: Sequence[FakePassage], count: int) -> list[str]:
    """Return ``count`` questions a student could ask."""
    asked = unique([f"What should I remember about {topic(p.text)}?" for p in passages])
    asked = asked[:count]
    while len(asked) < count:
        asked.append(f"What is the main idea of part {len(asked) + 1}?")
    return asked


# - - - Guides and summaries - - -


def build_guide(passages: Sequence[FakePassage], _: str) -> Document:
    """The source guide (§ 3.2.5)."""
    return {
        "summary": summary_text(passages, 70, 100),
        "key_topics": topics(passages, 5, 8),
        "questions": questions(passages, 3),
    }


def build_summary(passages: Sequence[FakePassage], _: str) -> Document:
    """The notebook title, emoji and overview (§ 3.2.6)."""
    text = summary_text(passages, 90, 130).split()
    bold = " ".join(text[:3])
    rest = " ".join(text[3:])
    return {
        "title": title_of(passages),
        "emoji": EMOJI,
        "summary": f"**{bold}** {rest}",
        "key_topics": topics(passages, 6, 10),
        "suggested_questions": questions(passages, 4),
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


def build_mind_map(passages: Sequence[FakePassage], _: str) -> Document:
    """A root, up to four main concepts and one detail under each (§ 3.4.2)."""
    root = passages[0]
    title = title_of(passages)
    nodes = [_node(1, None, title, root, DEMO_NOTE)]
    main = passages[:4]
    for index, passage in enumerate(main):
        label = topic(passage.text)
        if label == title:  # the first concept must not repeat the root
            label = clip_words(first_sentence(passage.text), TOPIC_WORDS).rstrip(",;:.")
        nodes.append(_node(2 + index, 1, label, passage, first_sentence(passage.text)))
    for index, passage in enumerate(main):
        detail = _detail(passage.text)
        nodes.append(
            _node(
                2 + len(main) + index,
                2 + index,
                clip_words(detail, TOPIC_WORDS).rstrip(",;:."),
                passage,
                detail,
            )
        )
    return {"title": title_of(passages), "nodes": nodes}


def _detail(text: str) -> str:
    """Return the second statement, else the first one."""
    parts = statements(text)
    if len(parts) > 1:
        return parts[1]
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
    if " — " in statement:
        front, back = statement.split(" — ", 1)
        return front.strip(), back.strip()
    words = statement.split()
    if "=" in statement and len(words) < 8:
        return f"{statement.split('=', 1)[0].strip()} = ?", statement
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


def _choice_question(
    index: int, statement: Statement, others: Sequence[str]
) -> Document:
    """A single choice question whose right answer is the statement."""
    wrong = [text for text in others if text.casefold() != statement.text.casefold()]
    wrong = wrong[: len(LETTERS) - 1]
    slot = (index - 1) % (len(wrong) + 1)
    texts = [*wrong[:slot], statement.text, *wrong[slot:]]
    return {
        "id": f"q{index}",
        "type": "single",
        "prompt": (
            f"Which statement about «{topic(statement.passage.text)}» "
            "matches the sources?"
        ),
        "options": [
            {"id": LETTERS[n], "text": clip(t, 200)} for n, t in enumerate(texts)
        ],
        "correct": [LETTERS[slot]],
        "explanation": f"{DEMO}: the source says «{clip_words(statement.text, 40)}».",
        "hint": f"{DEMO}: re-read «{topic(statement.passage.text)}».",
        "difficulty": "easy",
        "topic": clip(topic(statement.passage.text), 40),
        "refs": statement.passage.refs,
    }


def _true_false_question(index: int, statement: Statement) -> Document:
    """A true/false question about one statement (always true: it is quoted)."""
    return {
        "id": f"q{index}",
        "type": "true_false",
        "prompt": f"True or false: {clip(statement.text, 300)}",
        "options": [{"id": "true", "text": "True"}, {"id": "false", "text": "False"}],
        "correct": ["true"],
        "explanation": f"{DEMO}: the source says exactly this.",
        "hint": f"{DEMO}: re-read «{topic(statement.passage.text)}».",
        "difficulty": "easy",
        "topic": clip(topic(statement.passage.text), 40),
        "refs": statement.passage.refs,
    }


def build_quiz(passages: Sequence[FakePassage], _: str) -> Document:
    """Single choice questions over the statements; true/false when they are few."""
    found = teachable(all_statements(passages))
    chosen = found[:MAX_QUESTIONS]
    pool = unique([s.text for s in found])
    items: list[Document] = []
    for index, statement in enumerate(chosen, start=1):
        others = [t for t in pool if t.casefold() != statement.text.casefold()]
        if len(others) >= 1 and index % 3:
            items.append(_choice_question(index, statement, others))
        else:
            items.append(_true_false_question(index, statement))
    return {"title": f"{title_of(passages)}: demo quiz", "questions": items}


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
    gist = clip(first_sentence(text), 180)
    return f"{DEMO}. Explain this slide in your own words: {gist}"


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
    """Up to 3 topic labels over the <source> tags, in ``language``."""
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


Builder = Callable[[Sequence[FakePassage], str], Document]

BUILDERS: dict[str, Builder] = {
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
    if builder is build_labels:
        return build_labels(
            document_passages(messages),
            last_user_text(messages),
            label_language(messages),
        )
    return builder(document_passages(messages), last_user_text(messages))
