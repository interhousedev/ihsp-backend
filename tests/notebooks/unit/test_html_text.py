"""NB-17: the main text of an HTML page (URL sources, § 3.2.1)."""

import time

from app.modules.notebooks.infrastructure.html_text import (
    TITLE_LIMIT,
    ExtractedHtml,
    extract_html,
)

import pytest


def _text(markup: str) -> str:
    return extract_html(markup).text


# - - - Title - - -


def test_title_is_collapsed_and_decoded() -> None:
    """NB-17: the title is the <title> text, white space collapsed, entities decoded."""
    markup = "<head><title>\n  Cells &amp;\n   Tissues </title></head><p>x</p>"

    assert extract_html(markup).title == "Cells & Tissues"


def test_title_is_cut_to_200_characters() -> None:
    """NB-17: a very long title is cut."""
    markup = f"<title>{'x' * 500}</title><p>body</p>"

    assert extract_html(markup).title == "x" * TITLE_LIMIT


@pytest.mark.parametrize(
    "markup",
    ["<p>no title</p>", "<title></title><p>x</p>", "<svg><title>icon</title></svg>"],
)
def test_missing_or_empty_title_is_none(markup: str) -> None:
    """NB-17: no <title> (or an empty or SVG one) gives None."""
    assert extract_html(markup).title is None


def test_title_text_is_not_part_of_the_body() -> None:
    """NB-17: the title is not repeated in the text."""
    result = extract_html("<title>Only title</title><body><p>Body</p></body>")

    assert result == ExtractedHtml(title="Only title", text="Body")


def test_unclosed_title_does_not_swallow_the_page() -> None:
    """NB-17: a title that never ends is read as markup, the page stays readable."""
    result = extract_html("<title>Oops<p>Real content</p>")

    assert result.title is None
    assert "Real content" in result.text


# - - - What is dropped - - -


@pytest.mark.parametrize(
    "tag",
    [
        "script",
        "style",
        "noscript",
        "svg",
        "iframe",
        "canvas",
        "template",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "button",
    ],
)
def test_ignored_elements_are_dropped(tag: str) -> None:
    """NB-17: scripts, styles and page furniture are not text."""
    markup = f"<body><p>Keep</p><{tag}>Drop <b>this</b></{tag}><p>Also keep</p></body>"

    assert _text(markup) == "Keep\n\nAlso keep"


def test_script_content_is_not_parsed_as_markup() -> None:
    """NB-17: tags inside a script do not leak."""
    markup = '<p>a</p><script>document.write("</p><p>evil</p>")</script><p>b</p>'

    assert _text(markup) == "a\n\nb"


def test_nested_ignored_elements_are_dropped_to_the_matching_end() -> None:
    """NB-17: a nested <nav> inside a <nav> does not end the dropped part early."""
    markup = "<nav>a<nav>b</nav>c</nav><p>kept</p>"

    assert _text(markup) == "kept"


@pytest.mark.parametrize(
    "attributes",
    [
        "hidden",
        'hidden="hidden"',
        'aria-hidden="true"',
        'style="display:none"',
        'style="color: red; DISPLAY : NONE !important"',
        "style='display: none'",
    ],
)
def test_hidden_elements_are_dropped(attributes: str) -> None:
    """NB-17: hidden, aria-hidden and display:none elements are not text."""
    markup = f"<p>shown</p><div {attributes}><p>secret</p>more secret</div><p>end</p>"

    assert _text(markup) == "shown\n\nend"


def test_aria_hidden_false_is_kept() -> None:
    """NB-17: only aria-hidden="true" hides."""
    assert _text('<p aria-hidden="false">visible</p>') == "visible"


def test_hidden_element_inside_hidden_element_of_the_same_kind() -> None:
    """NB-17: nested divs inside a hidden div are dropped together."""
    markup = "<div hidden><div>a</div><div>b</div></div><p>kept</p>"

    assert _text(markup) == "kept"


def test_hidden_paragraph_without_end_tag_ends_at_the_next_paragraph() -> None:
    """NB-17: an omitted </p> must not hide the rest of the page."""
    assert (
        _text("<p hidden>secret<p>visible<p>also visible") == "visible\n\nalso visible"
    )


def test_images_and_link_targets_are_not_text() -> None:
    """NB-17: no alt text, no href: only the anchor text stays."""
    markup = (
        '<p>See <a href="https://x.test/secret">the guide</a>'
        '<img alt="logo" src="a.png"></p>'
    )

    assert _text(markup) == "See the guide"


def test_unclosed_nav_does_not_hide_the_rest_when_nothing_else_is_left() -> None:
    """NB-17: a page wrapped in an unclosed <nav> is read again without it."""
    assert _text("<nav><p>Only content</p>") == "Only content"


def test_page_wrapped_in_a_form_is_still_read() -> None:
    """NB-17: some sites wrap the whole body in <form>; the text must not vanish."""
    markup = '<body><form runat="server"><h1>Title</h1><p>Text</p></form></body>'

    assert _text(markup) == "# Title\n\nText"


def test_unclosed_navigation_ends_at_the_end_of_the_body() -> None:
    """NB-17: </body> ends a dropped element that was never closed."""
    markup = "<body><nav><a>x</a></body><p>after</p>"

    assert "after" in _text(markup)


# - - - Structure - - -


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5, 6])
def test_headings_become_markdown_lines(level: int) -> None:
    """NB-17: h1..h6 become # .. ###### lines."""
    markup = f"<h{level}>Heading <i>one</i></h{level}><p>text</p>"

    assert _text(markup) == f"{'#' * level} Heading one\n\ntext"


def test_paragraphs_and_divs_are_separated_by_blank_lines() -> None:
    """NB-17: blocks are blank-line separated."""
    assert _text("<div>a</div><p>b</p><section>c</section>") == "a\n\nb\n\nc"


def test_inline_elements_do_not_split_a_paragraph() -> None:
    """NB-17: bold, links and spans stay in one line."""
    markup = "<p>one <b>two</b><i>three</i> <a href='#'>four</a> <span>five</span></p>"

    assert _text(markup) == "one twothree four five"


def test_whitespace_is_collapsed_and_entities_decoded() -> None:
    """NB-17: runs of white space become one space; &nbsp; &amp; &#233; are decoded."""
    markup = "<p>  a \n\t b&nbsp;&nbsp;c &amp; d &#233; &lt;e&gt; </p>"

    assert _text(markup) == "a b c & d é <e>"


def test_line_break_becomes_a_newline() -> None:
    """NB-17: <br> starts a new line inside the block."""
    assert _text("<p>one<br>two<br/>three</p>") == "one\ntwo\nthree"


def test_list_items_are_dash_lines() -> None:
    """NB-17: list items are "- " lines, one after another."""
    markup = (
        "<p>Intro</p><ul><li>one</li><li>two <b>bold</b></li></ul>"
        "<ol><li>three</li></ol>"
    )

    assert _text(markup) == "Intro\n\n- one\n- two bold\n\n- three"


def test_nested_list_items_are_indented() -> None:
    """NB-17: nested lists are indented by two spaces per level."""
    markup = "<ul><li>a<ul><li>b</li></ul></li><li>c</li></ul>"

    assert _text(markup) == "- a\n  - b\n- c"


def test_list_items_without_end_tags() -> None:
    """NB-17: </li> may be left out."""
    assert _text("<ul><li>one<li>two<li>three</ul>") == "- one\n- two\n- three"


def test_table_rows_are_lines_with_tab_separated_cells() -> None:
    """NB-17: a table row is one line, cells joined by a tab."""
    markup = (
        "<table><thead><tr><th>Name</th><th>Role</th></tr></thead>"
        "<tbody><tr><td>ATP</td><td>energy</td></tr>"
        "<tr><td>DNA</td><td>genes</td></tr></tbody></table>"
    )

    assert _text(markup) == "Name\tRole\nATP\tenergy\nDNA\tgenes"


def test_empty_table_cells_keep_the_columns() -> None:
    """NB-17: an empty cell in the middle keeps its tab."""
    markup = "<table><tr><td>a</td><td></td><td>c</td></tr></table>"

    assert _text(markup) == "a\t\tc"


def test_table_cells_with_paragraphs_stay_on_one_line() -> None:
    """NB-17: block elements inside a cell do not break the row."""
    markup = (
        "<table><tr><td><p>one</p><p>two</p></td><td><div>three</div></td></tr></table>"
    )

    assert _text(markup) == "one two\tthree"


def test_table_without_end_tags() -> None:
    """NB-17: omitted </td> and </tr> still give rows."""
    assert _text("<table><tr><td>a<td>b<tr><td>c<td>d</table>") == "a\tb\nc\td"


def test_preformatted_text_keeps_its_lines_and_indentation() -> None:
    """NB-17: <pre> is kept, as a fenced block."""
    markup = "<p>Code:</p><pre>def f():\n    return 1\n</pre><p>after</p>"

    assert _text(markup) == "Code:\n\n```\ndef f():\n    return 1\n```\n\nafter"


def test_markup_inside_pre_does_not_split_it() -> None:
    """NB-17: tags inside <pre> are formatting, not blocks."""
    markup = "<pre><code>a = 1\n<b>b</b> = 2</code></pre>"

    assert _text(markup) == "```\na = 1\nb = 2\n```"


def test_inline_code_gets_backticks() -> None:
    """NB-17: <code> is kept, marked with backticks."""
    assert _text("<p>Call <code>print()</code> now</p>") == "Call `print()` now"


def test_empty_inline_code_vanishes() -> None:
    """NB-17: an empty <code> leaves no marks and no double space."""
    assert _text("<p>a <code></code> b</p>") == "a b"


def test_main_is_preferred_over_the_rest_of_the_body() -> None:
    """NB-17: the content of <main> is the page text."""
    markup = (
        "<body><div>Sidebar</div><main><h1>Real</h1><p>text</p></main>"
        "<div>Ads</div></body>"
    )

    assert _text(markup) == "# Real\n\ntext"


def test_article_is_preferred_when_there_is_no_main() -> None:
    """NB-17: the content of <article> is the page text."""
    markup = "<body><p>Menu</p><article><p>Story</p></article><p>Comments</p></body>"

    assert _text(markup) == "Story"


def test_several_articles_are_all_kept() -> None:
    """NB-17: a page with many articles keeps them in order."""
    markup = "<p>x</p><article><p>one</p></article><article><p>two</p></article>"

    assert _text(markup) == "one\n\ntwo"


def test_body_text_is_used_without_main_or_article() -> None:
    """NB-17: no main, no article: the whole body."""
    assert _text("<body><div>a</div><div>b</div></body>") == "a\n\nb"


def test_cyrillic_and_uzbek_text_is_kept() -> None:
    """NB-17: non-ASCII text passes through unchanged."""
    assert _text("<p>Ячейка — основа жизни. O‘zbekiston</p>") == (
        "Ячейка — основа жизни. O‘zbekiston"
    )


def test_control_and_zero_width_characters_are_removed() -> None:
    """NB-17: NUL, zero-width spaces, BOM and soft hyphens are removed."""
    assert _text("<p>a\x00b​c﻿d\xade</p>") == "abcde"


def test_page_without_text_gives_empty_text() -> None:
    """NB-17: nothing readable is not an error here."""
    assert extract_html("<script>x()</script><style>p{}</style>") == ExtractedHtml(
        title=None, text=""
    )


def test_empty_input() -> None:
    """NB-17: an empty page gives an empty result."""
    assert extract_html("") == ExtractedHtml(title=None, text="")


def test_plain_text_without_markup() -> None:
    """NB-17: text without any tags is returned as it is."""
    assert _text("just   some\ntext") == "just some text"


# - - - Broken markup - - -


@pytest.mark.parametrize(
    ("markup", "expected"),
    [
        ("<p>a<b>bold<i>both</p><p>b", "aboldboth\n\nb"),
        ("<p>1 < 2 and 3 <4 </p>", "1 < 2 and 3 <4"),
        ("<p>a</p><!-- hidden -->b", "a\n\nb"),
        ("<!DOCTYPE html><p>a</p>", "a"),
        ("<p>a</p><![CDATA[ x ]]><p>b</p>", "a\n\nb"),
        ("<p>a</p><?php echo 1; ?><p>b</p>", "a\n\nb"),
        ("<p>a</p></div></span></p><p>b</p>", "a\n\nb"),
        ('<p>a</p><p class="x>b</p>', "a\n\nb"),
        ("<p>a</p><p b", "a"),
        ("<p>a</p><!-- never closed <p>b</p>", "a"),
        ("<p>a</p><script>never closed <p>b</p>", "a"),
        ("</>text", "text"),
        ("x<", "x<"),
        ("<p>a</p></", "a"),
    ],
)
def test_broken_markup_is_tolerated(markup: str, expected: str) -> None:
    """NB-17: broken markup never raises; constructs that never end are dropped."""
    assert _text(markup) == expected


def test_attribute_values_may_contain_a_greater_than_sign() -> None:
    """NB-17: a quoted attribute value does not end the tag."""
    assert _text("<p title=\"a > b\" data-x='<i>'>text</p>") == "text"


def test_unquoted_attribute_values_and_stray_quotes() -> None:
    """NB-17: odd attribute syntax is tolerated."""
    assert _text('<p class=a"b id=c>text</p><p>next</p>') == "text\n\nnext"


def test_same_input_gives_same_output() -> None:
    """NB-17: the result is deterministic."""
    markup = (
        "<main><h1>A</h1><ul><li>b</li></ul><table><tr><td>c</td></tr></table></main>"
    )

    assert extract_html(markup) == extract_html(markup)


# - - - Performance - - -

_BIG = 2_000_000

_HOSTILE = {
    "unclosed tags": "<a " * (_BIG // 3),
    "unclosed comments": "<!--" * (_BIG // 4),
    "unclosed quotes": '<a href="' * (_BIG // 9),
    "unclosed declarations": "<!" * (_BIG // 2),
    "processing instructions": "<?" * (_BIG // 2),
    "cdata": "<![CDATA[" * (_BIG // 9),
    "less-than signs": "<" * _BIG,
    "less-than digits": "<3" * (_BIG // 2),
    "unclosed titles": "<title>" * (_BIG // 7),
    "unclosed scripts": "<script>" * (_BIG // 8),
    "ampersands": "&" * _BIG,
    "numeric entities": "&#" * (_BIG // 2),
    "deep nesting": "<div>" * (_BIG // 5),
    "hidden nesting": "<div hidden>" * (_BIG // 12),
    "unclosed code": "<p>" + "<code>" * (_BIG // 6),
    "headings": "<h1>" * (_BIG // 4),
    "list items": "<ul><li>" * (_BIG // 8),
    "table cells": "<table><tr><td>" * (_BIG // 15),
    "attribute noise": "<a " + "x=1 " * (_BIG // 4) + ">",
}


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(_HOSTILE))
def test_two_megabytes_of_hostile_markup_take_linear_time(name: str) -> None:
    """NB-17, § 3.7: no input makes the scan quadratic (stdlib HTMLParser does)."""
    markup = _HOSTILE[name]
    started = time.process_time()

    extract_html(markup)

    assert time.process_time() - started < 20.0


@pytest.mark.slow
def test_two_megabytes_of_ordinary_markup_are_read_in_seconds() -> None:
    """NB-17: a realistic 2 MB page is read fast."""
    row = (
        "<div><h2>Title</h2><p>Some <b>bold</b> text &amp; "
        "<a href='x'>link</a>.</p></div>\n"
    )
    markup = row * (_BIG // len(row))
    started = time.process_time()

    result = extract_html(markup)

    assert time.process_time() - started < 20.0
    assert result.text.startswith("## Title\n\nSome bold text & link.")
