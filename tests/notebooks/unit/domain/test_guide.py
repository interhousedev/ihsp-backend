"""NB-12, NB-13: source guide and notebook summary parsing and schemas (§ 3.2.5-6)."""

from datetime import UTC, datetime
from typing import Any

from app.modules.notebooks.domain.errors import OutputInvalidError
from app.modules.notebooks.domain.guide import (
    GUIDE_SCHEMA_NAME,
    SUMMARY_SCHEMA_NAME,
    guide_schema,
    parse_guide,
    parse_summary,
    single_emoji,
    summary_schema,
)
from app.modules.notebooks.domain.limits import DEFAULT_NOTEBOOK_TITLE
from tests.notebooks.unit.domain.pack_support import assert_strict

import pytest

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


def guide_doc(**changes: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "summary": "Plants turn light into chemical energy.",
        "key_topics": ["Light reactions", "Calvin cycle"],
        "questions": ["Where do light reactions happen?"],
    }
    return doc | changes


def summary_doc(**changes: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "title": "Photosynthesis basics",
        "emoji": "🌱",
        "summary": "**Photosynthesis** turns light into sugar.",
        "key_topics": ["Chloroplast", "Light reactions"],
        "suggested_questions": ["What is the Calvin cycle?"],
    }
    return doc | changes


def test_schema_names_match_the_spec() -> None:
    """NB-12: the fake LLM and the use cases agree on these names."""
    assert GUIDE_SCHEMA_NAME == "nb_guide"
    assert SUMMARY_SCHEMA_NAME == "nb_summary"


def test_guide_schema_is_strict_with_the_documented_fields() -> None:
    """NB-12: summary, key_topics, questions; every property required."""
    schema = guide_schema()

    assert_strict(schema)
    assert list(schema["properties"]) == ["summary", "key_topics", "questions"]
    assert schema["properties"]["key_topics"]["type"] == "array"


def test_summary_schema_is_strict_with_the_documented_fields() -> None:
    """NB-13: title, emoji, summary, key_topics, suggested_questions."""
    schema = summary_schema()

    assert_strict(schema)
    assert list(schema["properties"]) == [
        "title",
        "emoji",
        "summary",
        "key_topics",
        "suggested_questions",
    ]


def test_parse_guide_keeps_a_valid_document() -> None:
    """NB-12: a good guide passes unchanged."""
    guide = parse_guide(guide_doc())

    assert guide.summary == "Plants turn light into chemical energy."
    assert guide.key_topics == ["Light reactions", "Calvin cycle"]
    assert guide.questions == ["Where do light reactions happen?"]


def test_parse_guide_trims_lists_to_their_maxima() -> None:
    """NB-12: at most 8 topics and 3 questions."""
    doc = guide_doc(
        key_topics=[f"Topic {n}" for n in range(12)],
        questions=[f"Question {n}?" for n in range(6)],
    )

    guide = parse_guide(doc)

    assert guide.key_topics == [f"Topic {n}" for n in range(8)]
    assert guide.questions == [f"Question {n}?" for n in range(3)]


def test_parse_guide_drops_empty_blank_repeated_and_non_string_items() -> None:
    """NB-12: only real, distinct strings stay; empties do not use up the maximum."""
    doc = guide_doc(
        key_topics=["", "  ", "Cells", "cells", 5, None, "  Mitosis   cycle "],
        questions=[None, "Why?"],
    )

    guide = parse_guide(doc)

    assert guide.key_topics == ["Cells", "Mitosis cycle"]
    assert guide.questions == ["Why?"]


def test_parse_guide_treats_a_non_list_field_as_empty() -> None:
    """NB-12: a soft repair, not a failure."""
    guide = parse_guide(guide_doc(key_topics="Cells", questions=None))

    assert guide.key_topics == []
    assert guide.questions == []


def test_parse_guide_keeps_the_markdown_line_breaks_of_the_summary() -> None:
    """NB-12: the summary is Markdown."""
    guide = parse_guide(guide_doc(summary="  First.\n\n- second\n"))

    assert guide.summary == "First.\n\n- second"


@pytest.mark.parametrize("summary", [None, "", "   \n", 12, ["x"]])
def test_parse_guide_without_summary_text_is_invalid(summary: Any) -> None:
    """NB-12: an unusable document triggers the repair call."""
    with pytest.raises(OutputInvalidError) as caught:
        parse_guide(guide_doc(summary=summary))

    assert caught.value.problems


def test_parse_guide_rejects_a_non_object() -> None:
    """NB-12: the answer must be a JSON object."""
    with pytest.raises(OutputInvalidError):
        parse_guide(["not", "an", "object"])  # type: ignore[arg-type]


def test_parse_summary_returns_title_emoji_and_the_summary_payload() -> None:
    """NB-13: ParsedSummary carries the proposal and the stored payload."""
    parsed = parse_summary(summary_doc(), NOW)

    assert parsed.title == "Photosynthesis basics"
    assert parsed.emoji == "🌱"
    assert parsed.summary.summary == "**Photosynthesis** turns light into sugar."
    assert parsed.summary.key_topics == ["Chloroplast", "Light reactions"]
    assert parsed.summary.suggested_questions == ["What is the Calvin cycle?"]
    assert parsed.summary.generated_at == NOW


def test_parse_summary_trims_lists_to_their_maxima() -> None:
    """NB-13: at most 10 topics and 6 suggested questions."""
    doc = summary_doc(
        key_topics=[f"Topic {n}" for n in range(15)],
        suggested_questions=[f"Question {n}?" for n in range(9)],
    )

    parsed = parse_summary(doc, NOW)

    assert len(parsed.summary.key_topics) == 10
    assert parsed.summary.suggested_questions[-1] == "Question 5?"
    assert len(parsed.summary.suggested_questions) == 6


def test_parse_summary_cuts_the_title_to_120_characters() -> None:
    """NB-13: titles are at most 120 characters, on one line."""
    parsed = parse_summary(summary_doc(title="Very\nlong " * 40), NOW)

    assert len(parsed.title) == 120
    assert "\n" not in parsed.title
    assert parsed.title.endswith("…")


def test_parse_summary_without_title_uses_the_first_topic_then_the_default() -> None:
    """NB-13: the title is applied only for auto titles, so it is never empty."""
    with_topic = parse_summary(summary_doc(title="  "), NOW)
    without = parse_summary(summary_doc(title=None, key_topics=[]), NOW)

    assert with_topic.title == "Chloroplast"
    assert without.title == DEFAULT_NOTEBOOK_TITLE


@pytest.mark.parametrize("summary", [None, "", "  ", 3])
def test_parse_summary_without_summary_text_is_invalid(summary: Any) -> None:
    """NB-13: no summary, no use."""
    with pytest.raises(OutputInvalidError):
        parse_summary(summary_doc(summary=summary), NOW)


def test_parse_summary_with_a_bad_emoji_keeps_the_rest() -> None:
    """NB-13: the emoji is optional."""
    parsed = parse_summary(summary_doc(emoji="biology"), NOW)

    assert parsed.emoji is None
    assert parsed.summary.summary


def test_parse_summary_with_a_non_string_emoji_gives_none() -> None:
    """NB-13: numbers and nulls are ignored."""
    assert parse_summary(summary_doc(emoji=None), NOW).emoji is None
    assert parse_summary(summary_doc(emoji=7), NOW).emoji is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("📚", "📚"),
        ("  🔬  ", "🔬"),
        ("📚🔬", "📚"),
        ("📚 Biology", "📚"),
        ("❤️", "❤️"),
        ("☀", "☀"),
        ("👍🏽", "👍🏽"),
        ("👨‍👩‍👧", "👨‍👩‍👧"),
        ("🇺🇿", "🇺🇿"),
        ("🇺", None),
        ("1️⃣", "1️⃣"),
        ("1", None),
        ("A", None),
        ("©", None),
        ("biology 📚", None),
        ("", None),
        ("   ", None),
        ("‍", None),
    ],
)
def test_single_emoji_keeps_one_grapheme_or_nothing(
    value: str, expected: str | None
) -> None:
    """NB-13: the first emoji sequence survives whole; anything else is dropped."""
    assert single_emoji(value) == expected
