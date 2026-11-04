"""Markdown and OpenUI tables render as one monospace block, text around them too."""

from app.interfaces.bot.richtext import render_telegram

TABLE = "| Day | Mark |\n| --- | ---: |\n| Mon | 5 |\n| Tuesday | 4 |"


def _joined(markdown: str) -> str:
    return "\n".join(chunk.text for chunk in render_telegram(markdown))


def test_a_markdown_table_is_a_pre_block_with_aligned_columns() -> None:
    html = _joined(TABLE)
    assert html.startswith("<pre>") and html.endswith("</pre>")
    rows = html[len("<pre>") : -len("</pre>")].split("\n")
    assert rows[0].startswith("Day ") and "Mark" in rows[0]
    assert set(rows[1].replace(" ", "")) <= {"-"}  # the rule under the header
    assert rows[2].index("5") == rows[0].index("Mark")
    assert "|" not in html


def test_text_around_a_table_stays_as_rich_text() -> None:
    html = _joined(f"**Timetable** for today\n\n{TABLE}\n\nSee *notes* below.")
    assert html.startswith("<b>Timetable</b> for today")
    assert "<pre>" in html and "<i>notes</i>" in html
    assert html.index("<pre>") < html.index("See")


def test_cell_text_is_escaped_and_loses_its_markdown_markers() -> None:
    html = _joined("| a | b |\n|---|---|\n| <x> & **bold** | `code` |")
    assert "&lt;x&gt; &amp; bold" in html
    assert "<b>" not in html and "<code>" not in html


def test_a_header_line_without_a_rule_is_plain_text() -> None:
    html = _joined("| a | b |\nnot a rule")
    assert "<pre>" not in html
    assert "| a | b |" in html


def test_a_table_answer_and_a_plain_answer_use_the_same_chunking() -> None:
    long_table = "\n".join(f"| row {i} | {'x' * 40} |" for i in range(200))
    markdown = f"| h | v |\n|---|---|\n{long_table}"
    chunks = render_telegram(markdown)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= 4096
        assert chunk.text.count("<pre>") == chunk.text.count("</pre>")
