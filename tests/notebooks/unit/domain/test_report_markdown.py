"""NB-22: Markdown clean-up of reports: raw HTML, heading cap, contents list."""

from app.modules.notebooks.domain.artifacts.report_markdown import (
    cap_headings,
    extract_headings,
    strip_citation_marks,
    strip_html,
)

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("a <b>bold</b> b", "a bold b"),
        ("a <B>bold</B> b", "a bold b"),
        ("line<br>break<br/>and<br />more", "line break and more"),
        ('<a href="http://x.y" onclick="z()">link</a>', "link"),
        ('<img src="x.png" alt="a > b">after', "after"),
        ("<span\nclass='x'>wrapped</span>", "wrapped"),
        ("text <!-- hidden\nacross lines --> more", "text  more"),
        ("<script>\nalert(1)\n</script>after", "after"),
        ("<style>p{color:red}</style>after", "after"),
    ],
)
def test_strip_html_removes_tags_comments_and_active_blocks(
    raw: str, clean: str
) -> None:
    """NB-22: no raw HTML survives outside code."""
    assert strip_html(raw) == clean


@pytest.mark.parametrize(
    "text",
    [
        "type <name> here",
        "if a < b and c > d",
        "write x<y>z",
        "<unknown-element>kept</unknown-element>",
        "Generic<T> in Java",
    ],
)
def test_strip_html_keeps_angle_brackets_that_are_not_html(text: str) -> None:
    """NB-22: placeholders and comparisons are not tags."""
    assert strip_html(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "```html\n<div>x</div>\n```",
        "~~~\n<script>alert(1)</script>\n~~~",
        "````\n```\n<b>x</b>\n```\n````",
        "text\n```\n<b>unclosed fence runs to the end",
        "Use `<div>` and ``<span>`` tags",
    ],
)
def test_strip_html_leaves_code_alone(text: str) -> None:
    """NB-22: fenced blocks (any fence) and inline code spans are verbatim."""
    assert strip_html(text) == text


def test_strip_html_cleans_text_around_a_fence() -> None:
    """NB-22: prose before and after a code block is still cleaned."""
    raw = "<b>a</b>\n```\n<b>code</b>\n```\n<i>b</i>"

    assert strip_html(raw) == "a\n```\n<b>code</b>\n```\nb"


def test_a_shorter_closing_fence_does_not_end_a_longer_block() -> None:
    """NB-22: ``` inside ```` stays code."""
    raw = "````\n```\n<b>x</b>\n````\n<b>y</b>"

    assert strip_html(raw) == "````\n```\n<b>x</b>\n````\ny"


def test_strip_citation_marks_removes_model_written_chips_only() -> None:
    """NB-22: ⟦1⟧ and ⟦1,2⟧ go; [[S1:P1]] stays for the processor."""
    assert strip_citation_marks("a ⟦1⟧ b ⟦1,2⟧ c [[S1:P1]]") == "a  b  c [[S1:P1]]"


def test_cap_headings_keeps_the_first_n() -> None:
    """NB-22: the n-th heading is still a heading."""
    text = "\n".join(f"## H{n}" for n in range(1, 6))

    capped = cap_headings(text, limit=3)

    assert capped.splitlines() == ["## H1", "## H2", "## H3", "**H4**", "**H5**"]


def test_cap_headings_ignores_code_and_counts_all_levels() -> None:
    """NB-22: only real headings count."""
    text = "# A\n```\n# in code\n# in code\n```\n### B\n#### C ####"

    capped = cap_headings(text, limit=2)

    assert capped.splitlines() == [
        "# A",
        "```",
        "# in code",
        "# in code",
        "```",
        "### B",
        "**C**",
    ]


def test_cap_headings_under_the_limit_changes_nothing() -> None:
    """NB-22: idempotent for short documents."""
    text = "# A\n\ntext\n\n## B"

    assert cap_headings(text) == text


def test_extract_headings_skips_code_and_text_without_content() -> None:
    """NB-22: a heading needs text outside code; # alone and #hashtags are text."""
    text = "# Real\n```\n# fake\n```\n#hashtag\n##\n## ⟦1⟧\n    # indented code"

    headings = extract_headings(text)

    assert [(h.level, h.text) for h in headings] == [(1, "Real")]


def test_extract_headings_ids_never_collide() -> None:
    """NB-22: suffixes avoid headings that already look like a suffixed slug."""
    headings = extract_headings("## A\n## A\n## A 2\n## A")

    assert [h.id for h in headings] == ["a", "a-2", "a-2-2", "a-3"]


def test_extract_headings_without_letters_gets_a_section_id() -> None:
    """NB-22: an emoji heading still has an anchor."""
    headings = extract_headings("## 🌱\n## 🌿")

    assert [h.id for h in headings] == ["section", "section-2"]


def test_extract_headings_as_dict_has_the_stored_shape() -> None:
    """NB-22: {level, text, id}."""
    (heading,) = extract_headings("### Light reactions")

    assert heading.as_dict() == {
        "level": 3,
        "text": "Light reactions",
        "id": "light-reactions",
    }


@settings(max_examples=150, deadline=None)
@given(
    lines=st.lists(
        st.sampled_from(["# A", "## B", "text", "```", "~~~", "### C ###", "", "<b>x"]),
        max_size=60,
    ),
    limit=st.integers(1, 10),
)
def test_cap_headings_never_leaves_more_than_the_limit(
    lines: list[str], limit: int
) -> None:
    """NB-22: whatever the code fences do, the contents list stays within the cap."""
    capped = cap_headings("\n".join(lines), limit)

    assert len(extract_headings(capped)) <= limit
    assert len(extract_headings(strip_html(capped))) <= limit
