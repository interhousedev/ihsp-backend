"""Deterministic JSON documents for the notebook Studio, guides and summaries.

Used by ``FakeLlmGateway.complete_json``: every builder reads the passages found in
the prompt (``fake_sources``) and returns a valid document of the shape in the
notebooks spec (§ 3.2.5, § 3.2.6, § 3.4). Without labels the ``refs`` are empty.
"""

import json
import re
from collections.abc import Callable, Sequence
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
SUMMARY_FILLER = (
    "This overview was prepared automatically for quick revision of the source and "
    "repeats its main statements in short form so that a student can check the page "
    "without a real language model."
)
REPORT_INTRO = "These are the key points of this part of the sources, as short theses."

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[^\W_][\w'ʻʼ’-]*")


# - - - Text helpers - - -


def sentences(text: str) -> list[str]:
    """Split text into sentences after collapsing whitespace; never empty."""
    flat = " ".join(text.split())
    parts = [part for part in _SENTENCE_END.split(flat) if part]
    return parts or [flat]


def first_sentence(text: str) -> str:
    """Return the first sentence."""
    return sentences(text)[0]


def head_words(text: str, count: int) -> str:
    """Return the first ``count`` words without punctuation around them."""
    return " ".join(_WORD.findall(text)[:count])


def clip(text: str, limit: int) -> str:
    """Cut text to ``limit`` characters."""
    return text[:limit].rstrip()


def clip_words(text: str, limit: int) -> str:
    """Return the first ``limit`` words of a text."""
    return " ".join(text.split()[:limit])


def topic(text: str) -> str:
    """Return a 2 to 3 word label for a passage."""
    label = head_words(text, 3)
    if len(label.split()) < 2:
        label = f"{label} topic".strip() if label else "Main topic"
    return clip(label, 60)


def title_of(passages: Sequence[FakePassage]) -> str:
    """Return a 2 to 6 word title: the first words of the first passage."""
    words = head_words(passages[0].text, 4).split()
    if len(words) < 2:
        words = [*words, "notes"] if words else ["Study", "notes"]
    return " ".join(words)


def cited(passage: FakePassage) -> str:
    """Return the first sentence followed by its ``[[label]]`` marker."""
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


def summary_text(passages: Sequence[FakePassage], low: int, high: int) -> str:
    """Return ``low`` to ``high`` words made from the passages (padded if short)."""
    words: list[str] = []
    for passage in passages:
        words.extend(" ".join(passage.text.split()).split())
        if len(words) >= low:
            break
    while len(words) < low:
        words.extend(SUMMARY_FILLER.split())
    return " ".join(words[:high])


def topics(passages: Sequence[FakePassage], low: int, high: int) -> list[str]:
    """Return ``low`` to ``high`` distinct 2 to 5 word topics."""
    found = unique([topic(p.text) for p in passages])[:high]
    while len(found) < low:
        found.append(f"Key topic {len(found) + 1}")
    return found


def questions(passages: Sequence[FakePassage], count: int) -> list[str]:
    """Return ``count`` questions a student could ask."""
    asked = unique(
        [f"What does the source say about {topic(p.text)}?" for p in passages]
    )
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
    lines = [f"# {title}", "", "## Main idea", cited(passages[0]), ""]
    chosen = [cycle(passages, n) for n in range(max(len(passages), 3))][:12]
    for number in range(3):
        group = chosen[number::3]
        lines += [f"## {number + 1}. {topic(group[0].text)}", REPORT_INTRO, ""]
        lines += [f"- {cited(passage)}" for passage in group] + [""]
    return {"title": f"{title}: conspect", "markdown": "\n".join(lines).strip()}


def build_mind_map(passages: Sequence[FakePassage], _: str) -> Document:
    """A root, up to four main concepts and one detail under each (§ 3.4.2)."""
    root = passages[0]
    nodes = [_node(1, None, title_of(passages), root, first_sentence(root.text))]
    main = passages[:4]
    for index, passage in enumerate(main):
        nodes.append(
            _node(
                2 + index, 1, topic(passage.text), passage, first_sentence(passage.text)
            )
        )
    for index, passage in enumerate(main):
        detail = _detail(passage.text)
        nodes.append(
            _node(
                2 + len(main) + index,
                2 + index,
                f"Detail: {head_words(detail, 3)}",
                passage,
                detail,
            )
        )
    return {"title": title_of(passages), "nodes": nodes}


def _detail(text: str) -> str:
    """Return the second sentence, else the passage without its first words."""
    parts = sentences(text)
    if len(parts) > 1:
        return parts[1]
    return " ".join(text.split()[3:]) or text


def _node(
    number: int, parent: int | None, label: str, passage: FakePassage, note: str
) -> Document:
    return {
        "id": f"n{number}",
        "parent_id": None if parent is None else f"n{parent}",
        "label": clip(label, 60),
        "note": clip(note, 200),
        "refs": passage.refs,
    }


# - - - Cards, quiz and table - - -


def _distinct_fronts(passages: Sequence[FakePassage]) -> list[str]:
    """One question per passage; repeats get the passage number."""
    fronts: list[str] = []
    for index, passage in enumerate(passages, start=1):
        about = head_words(passage.text, 3) or "this passage"
        front = f"What does the source say about {about}?"
        if front.casefold() in {f.casefold() for f in fronts}:
            front = f"{front[:-1]} ({index})?"
        fronts.append(clip(front, 160))
    return fronts


def build_flashcards(passages: Sequence[FakePassage], _: str) -> Document:
    """Cards from the first sentences of up to ten passages (§ 3.4.3)."""
    chosen = list(passages[:MAX_CARDS])
    cards = [
        {
            "id": f"c{index}",
            "front": front,
            "back": clip(first_sentence(passage.text), 300),
            "hint": "Think about the passage.",
            "topic": clip(head_words(passage.text, 2) or "Main topic", 40),
            "refs": passage.refs,
        }
        for index, (front, passage) in enumerate(
            zip(_distinct_fronts(chosen), chosen, strict=True), start=1
        )
    ]
    return {"title": f"{title_of(passages)}: cards", "cards": cards}


def _options(correct: str, others: Sequence[str], slot: int) -> list[str]:
    """Four option texts with the correct one in ``slot``; fillers are 'Option X'."""
    wrong = [text for text in unique(others) if text.casefold() != correct.casefold()]
    texts: list[str] = []
    for position in range(len(LETTERS)):
        if position == slot:
            texts.append(correct)
        else:
            texts.append(
                wrong.pop(0) if wrong else f"Option {LETTERS[position].upper()}"
            )
    return texts


def build_quiz(passages: Sequence[FakePassage], _: str) -> Document:
    """Single choice questions whose right answer is the passage's first sentence."""
    chosen = list(passages[:MAX_QUESTIONS])
    sentences_of = [clip(first_sentence(p.text), 200) for p in passages]
    items: list[Document] = []
    for index, (front, passage) in enumerate(
        zip(_distinct_fronts(chosen), chosen, strict=True), start=1
    ):
        slot = (index - 1) % len(LETTERS)
        others = [s for n, s in enumerate(sentences_of) if n != index - 1]
        correct_text = sentences_of[index - 1]
        texts = _options(correct_text, others, slot)
        items.append(
            {
                "id": f"q{index}",
                "type": "single",
                "prompt": front,
                "options": [{"id": LETTERS[n], "text": t} for n, t in enumerate(texts)],
                "correct": [LETTERS[slot]],
                "explanation": f"The source says: {clip_words(correct_text, 40)}",
                "hint": "Look at the beginning of the passage.",
                "difficulty": "easy",
                "topic": clip(head_words(passage.text, 2) or "Main topic", 40),
                "refs": passage.refs,
            }
        )
    return {"title": f"{title_of(passages)}: quiz", "questions": items}


def build_data_table(passages: Sequence[FakePassage], _: str) -> Document:
    """A term and definition table, one row per passage (§ 3.4.5)."""
    rows = [
        {
            "cells": {
                "term": clip(head_words(p.text, 3) or "Term", 120),
                "definition": clip(first_sentence(p.text), 120),
            },
            "refs": p.refs,
        }
        for p in passages[:MAX_ROWS]
    ]
    return {
        "title": f"{title_of(passages)}: terms",
        "columns": [
            {"key": "term", "label": "Term", "type": "text"},
            {"key": "definition", "label": "Definition", "type": "text"},
        ],
        "rows": rows,
    }


# - - - Slides and infographic - - -


def _bullets(text: str, limit: int = 3) -> list[str]:
    return [clip_words(s, 12) for s in sentences(text)[:limit]]


def _slide_notes(text: str) -> str:
    return f"Explain this slide in your own words. {clip(first_sentence(text), 200)}"


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
            "notes": "Welcome the class. Introduce the topic of this deck.",
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
    return {"title": title, "subtitle": "Study notebook", "slides": numbered}


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
    return {
        "head": clip(head if head is not None else head_words(passage.text, 2), 40),
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
        "subtitle": "Study notebook",
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
    """Up to 3 topic labels over the ``<source key=... title=...>`` tags, named in ``language``."""
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
