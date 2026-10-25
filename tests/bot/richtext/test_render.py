"""Markdown to Telegram HTML rendering, including math, buttons and chunking."""

import re

from app.interfaces.bot.richtext import (
    ButtonSpec,
    FormulaSpec,
    TelegramChunk,
    render_partial,
    render_telegram,
)

LOG_EXAMPLE = "$ \\log_2 8=3 $, потому что $2^3 = 8$"


def _texts(markdown: str) -> list[str]:
    return [chunk.text for chunk in render_telegram(markdown)]


def test_logarithm_example_renders_readable_unicode_without_eaten_spaces() -> None:
    chunks = render_telegram(LOG_EXAMPLE)

    assert chunks == [TelegramChunk(text="log₂ 8=3, потому что 2³ = 8")]


def test_inline_math_tolerates_spaces_inside_dollars() -> None:
    assert _texts("$\\log_2 8 = 3$") == ["log₂ 8 = 3"]


def test_dollar_amounts_are_not_treated_as_math() -> None:
    assert _texts("price $5 and $10") == ["price $5 and $10"]


def test_snake_case_identifiers_are_not_italic() -> None:
    assert _texts("snake_case_name") == ["snake_case_name"]


def test_display_math_block_is_rendered_as_code() -> None:
    chunk = render_telegram("$$\n2^3 = 8\n$$")[0]

    assert chunk.text == "<code>2³ = 8</code>"
    assert chunk.formulas == ()


def test_complex_display_formula_is_flagged_for_image_rendering() -> None:
    chunk = render_telegram("$$\\sum_{i=1}^{n} i$$")[0]

    assert chunk.formulas == (FormulaSpec(latex="\\sum_{i=1}^{n} i", display=True),)
    assert "∑" in chunk.text


def test_bold_italic_and_code_are_converted_and_escaped() -> None:
    result = _texts("**жирный** *курсив* `a<b`")

    assert result == ["<b>жирный</b> <i>курсив</i> <code>a&lt;b</code>"]


def test_raw_html_is_escaped_so_no_tags_are_injected() -> None:
    assert _texts("<script>alert(1)</script>") == [
        "&lt;script&gt;alert(1)&lt;/script&gt;"
    ]


def test_https_link_is_rendered_with_escaped_href() -> None:
    assert _texts("[site](https://x.uz/a?b=1&c=2)") == [
        '<a href="https://x.uz/a?b=1&amp;c=2">site</a>'
    ]


def test_link_with_quote_in_url_cannot_break_out_of_attribute() -> None:
    result = _texts('[s](https://x.uz/"onmouseover=1)')[0]

    assert 'href="https://x.uz/&quot;onmouseover=1"' in result


def test_http_and_javascript_links_keep_only_their_label() -> None:
    assert _texts("[s](http://x.uz)") == ["s"]
    assert _texts("[s](javascript:alert(1))") == ["s"]


def test_fenced_code_keeps_language_and_escapes_content() -> None:
    assert _texts("```python\nprint(1<2)\n```") == [
        '<pre><code class="language-python">print(1&lt;2)</code></pre>'
    ]


def test_heading_becomes_bold_line() -> None:
    assert _texts("## Тема") == ["<b>Тема</b>"]


def test_consecutive_quote_lines_form_one_blockquote() -> None:
    assert _texts("> a\n> b") == ["<blockquote>a\nb</blockquote>"]


def test_bullets_are_rendered_with_bullet_glyph() -> None:
    assert _texts("- один\n- два") == ["• один\n• два"]


def test_button_lines_are_removed_from_text_and_collected() -> None:
    chunks = render_telegram(
        "Выберите:\n[[button:Открыть|https://iht.uz]]\n[[button:Ок|ok:1]]"
    )

    assert chunks == [
        TelegramChunk(
            text="Выберите:",
            buttons=(
                ButtonSpec(label="Открыть", url="https://iht.uz"),
                ButtonSpec(label="Ок", callback_data="ok:1"),
            ),
        )
    ]


def test_invalid_button_falls_back_to_plain_label() -> None:
    chunk = render_telegram("[[button:Плохая|http://evil.example]]")[0]

    assert chunk.buttons == ()
    assert chunk.text == "Плохая"


def test_partial_unclosed_fence_is_closed_by_renderer() -> None:
    assert render_partial("```py\nx = 1") == [
        TelegramChunk(text='<pre><code class="language-py">x = 1</code></pre>')
    ]


def test_partial_incomplete_button_line_is_hidden_while_streaming() -> None:
    assert [c.text for c in render_partial("Ответ\n[[button:Ещ")] == ["Ответ"]


def test_partial_unclosed_bold_stays_literal_text() -> None:
    assert _texts("**жир") == ["**жир"]


def test_long_text_is_split_into_chunks_within_limit() -> None:
    chunks = render_telegram("слово " * 2000)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 4096 for chunk in chunks)


def test_chunks_never_split_an_entity() -> None:
    chunks = render_telegram("a & b < c " * 1500)

    for chunk in chunks:
        assert re.search(r"&(?![#\w]+;)", chunk.text) is None


def test_chunks_never_split_a_tag() -> None:
    chunks = render_telegram("**жирный текст** " * 500)

    for chunk in chunks:
        assert chunk.text.count("<") == chunk.text.count(">")


def test_split_pre_block_reopens_the_code_tags_in_each_chunk() -> None:
    chunks = render_telegram("```python\n" + "x = 1\n" * 1200 + "```")

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.startswith('<pre><code class="language-python">')
        assert chunk.text.endswith("</code></pre>")
        assert len(chunk.text) <= 4096


def test_buttons_are_attached_to_the_last_chunk() -> None:
    markdown = "слово " * 2000 + "\n[[button:Далее|next:1]]"

    chunks = render_telegram(markdown)

    assert len(chunks) > 1
    assert chunks[-1].buttons == (ButtonSpec(label="Далее", callback_data="next:1"),)
    assert all(chunk.buttons == () for chunk in chunks[:-1])


def test_empty_markdown_renders_no_chunks() -> None:
    assert render_telegram("") == []
