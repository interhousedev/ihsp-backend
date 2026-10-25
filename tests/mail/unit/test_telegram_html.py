"""MAIL-2, MAIL-4: email HTML <-> Telegram's HTML subset."""

import re
from html.parser import HTMLParser

from app.modules.mail.domain.inbound_message import parse_message
from app.modules.mail.domain.telegram_html import (
    TELEGRAM_LIMIT,
    TELEGRAM_TAGS,
    html_to_telegram,
    html_to_text,
    plain_to_telegram,
    telegram_to_email_html,
)
from tests.mail.helpers import fixture_bytes

from hypothesis import given
from hypothesis import strategies as st

TAG_RE = re.compile(r"</?\s*([a-zA-Z0-9]+)")


class _Balance(HTMLParser):
    """Collects tag names and checks that tags are balanced."""

    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()
        self.stack: list[str] = []
        self.balanced = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.names.add(tag)
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        self.names.add(tag)
        if not self.stack or self.stack.pop() != tag:
            self.balanced = False


def inspect(html: str) -> _Balance:
    parser = _Balance()
    parser.feed(html)
    parser.close()
    return parser


def test_html_with_image_and_link_is_converted_to_allowed_tags_only() -> None:
    """MAIL-2: scripts, styles, images, tables, divs go; text and links stay."""
    parsed = parse_message(fixture_bytes("html_image_link.eml"))
    assert parsed.html is not None

    result = html_to_telegram(parsed.html)

    parser = inspect(result.html)
    assert parser.names <= TELEGRAM_TAGS
    assert parser.balanced and not parser.stack
    assert "<b>Aleksey</b>" in result.html
    assert '<a href="https://example.com/schedule?week=41&amp;group=2TN2">here</a>' in (
        result.html
    )
    for forbidden in (
        "<img",
        "<script",
        "alert",
        "<table",
        "<div",
        "javascript:",
        "ignore me",
    ):
        assert forbidden not in result.html
    assert not result.truncated


def test_block_tags_become_newlines_and_list_items_get_bullets() -> None:
    """MAIL-2: <p>, <div>, <br> and <li> turn into newlines."""
    html = "<div>one<br>two</div><p>three</p><ul><li>a</li><li>b</li></ul>"

    result = html_to_telegram(html)

    assert result.html == "one\ntwo\n\nthree\n\n• a\n• b"


def test_blank_lines_and_spaces_collapse() -> None:
    """MAIL-2: runs of blank lines and spaces are collapsed."""
    result = html_to_telegram("<p>a</p>\n\n\n<p>   </p><p>b   c&nbsp;d</p>")

    assert result.html == "a\n\nb c d"


def test_a_link_without_a_safe_scheme_loses_its_href() -> None:
    """MAIL-2: javascript: links are not forwarded."""
    result = html_to_telegram(
        '<a href="javascript:alert(1)">click</a> '
        '<a href="mailto:a@example.com">mail</a>'
    )

    assert result.html == 'click <a href="mailto:a@example.com">mail</a>'


def test_pre_blocks_keep_their_line_breaks_and_do_not_nest_tags() -> None:
    """MAIL-2: Telegram forbids entities inside code and pre."""
    result = html_to_telegram("<pre>line1\n  line2 <b>bold</b></pre>")

    assert result.html == "<pre>line1\n  line2 bold</pre>"


def test_empty_tags_are_dropped() -> None:
    """MAIL-2: <b></b> and empty links are removed."""
    result = html_to_telegram('x<b> </b><a href="https://example.com"></a>y')

    assert result.html == "xy"


def test_a_long_body_is_cut_on_a_tag_boundary_with_balanced_tags() -> None:
    """MAIL-2: more than 3500 characters -> truncated, tags closed."""
    html = "<b><i>" + "word &amp; <u>underlined</u> " * 400 + "</i></b>"

    result = html_to_telegram(html)

    assert result.truncated
    assert len(result.html) <= TELEGRAM_LIMIT
    parser = inspect(result.html)
    assert parser.balanced and not parser.stack
    assert result.html.endswith("…</i></b>")
    assert not re.search(
        r"&[a-z]*$", result.html.removesuffix("</i></b>").removesuffix("…")
    )


def test_a_cut_never_splits_an_entity() -> None:
    """MAIL-2: the text is cut before a half-written &amp;."""
    result = html_to_telegram("a" * 3496 + " &amp; more text", limit=3500)

    assert result.truncated
    assert "&am" not in result.html.replace("&amp;", "")


def test_a_short_body_is_not_truncated() -> None:
    """MAIL-2: truncated is False when everything fits."""
    assert not html_to_telegram("<p>short</p>").truncated


def test_no_limit_keeps_everything() -> None:
    """MAIL-4: forwarding quotes the whole body."""
    result = html_to_telegram("<p>" + "x " * 5000 + "</p>", limit=None)

    assert not result.truncated
    assert len(result.html) > 9000


def test_plain_text_is_escaped_for_telegram() -> None:
    """MAIL-2: a plain body keeps < > & as entities and its line breaks."""
    result = plain_to_telegram("1 < 2 & 3 > 2\r\nsecond line")

    assert result.html == "1 &lt; 2 &amp; 3 &gt; 2\nsecond line"


def test_html_to_text_writes_links_after_their_text() -> None:
    """MAIL-4: the plain alternative of an HTML mail keeps link targets."""
    text = html_to_text(
        '<p>See <a href="https://example.com/a?x=1&amp;y=2">the page</a>.</p><p>Bye</p>'
    )

    assert text == "See the page (https://example.com/a?x=1&y=2).\n\nBye"


def test_telegram_html_becomes_email_html_with_breaks() -> None:
    """MAIL-4: Telegram formatting is converted to HTML; newlines become <br>."""
    html = telegram_to_email_html(
        "Hi <b>there</b>\nsecond <script>x()</script>"
        '<a href="https://example.com">l</a>'
    )

    assert html == 'Hi <b>there</b><br>\nsecond <a href="https://example.com">l</a>'


def test_pre_blocks_in_email_html_keep_their_newlines() -> None:
    """MAIL-4: no <br> inside <pre>."""
    html = telegram_to_email_html("a\n<pre>x\ny</pre>\nb")

    assert html == "a<br>\n<pre>x\ny</pre><br>\nb"


@given(st.text(alphabet=st.characters(codec="utf-8"), max_size=300))
def test_any_input_gives_allowed_balanced_output(text: str) -> None:
    """MAIL-2 (property): output tags are allowed and balanced for any input."""
    html = (
        f"<div><b>{text}</b><i><a href='https://example.com'>{text}</a></i>{text}</div>"
    )

    result = html_to_telegram(html, limit=200)

    parser = inspect(result.html)
    assert parser.names <= TELEGRAM_TAGS
    assert parser.balanced and not parser.stack
    assert len(result.html) <= 200


def test_relative_and_unsafe_links_lose_their_href() -> None:
    """MAIL-2: only absolute http, https and mailto links reach Telegram."""
    html = (
        '<a href="/path">a</a> <a href="//evil.example/x">b</a> <a href="#top">c</a> '
        '<a href="tg://user?id=1">d</a> <a href="https://example.com/ok">e</a>'
    )

    result = html_to_telegram(html)

    assert result.html == 'a b c d <a href="https://example.com/ok">e</a>'
