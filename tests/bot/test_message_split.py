"""Splitting Telegram HTML at 4096 visible characters."""

from app.interfaces.bot.utilities.html import escape, shorten, visible_length
from app.interfaces.bot.utilities.message_split import split_html, truncate_html

from hypothesis import given
from hypothesis import strategies as st


def test_short_text_is_one_part() -> None:
    """Nothing to split."""
    assert split_html("<b>hi</b>") == ["<b>hi</b>"]


def test_empty_text_gives_one_empty_part() -> None:
    """The caller always gets at least one part."""
    assert split_html("") == [""]


def test_tags_do_not_count_towards_the_limit() -> None:
    """Telegram counts characters after parsing entities."""
    text = "<b>" + "a" * 10 + "</b>"

    assert split_html(text, limit=10) == [text]


def test_entities_count_as_one_character() -> None:
    """``&amp;`` is one character for Telegram."""
    assert split_html("&amp;" * 5, limit=5) == ["&amp;" * 5]


def test_long_text_is_cut_at_a_line_end() -> None:
    """Cuts happen between lines when possible."""
    text = "\n".join(["x" * 6] * 4)

    parts = split_html(text, limit=14)

    assert parts == ["xxxxxx\nxxxxxx\n", "xxxxxx\nxxxxxx"]


def test_open_tags_are_closed_and_reopened_at_a_cut() -> None:
    """A bold text spanning two parts is bold in both."""
    text = "<b>" + "a" * 6 + "\n" + "b" * 6 + "</b>"

    parts = split_html(text, limit=8)

    assert parts == ["<b>aaaaaa\n</b>", "<b>bbbbbb</b>"]


def test_an_attribute_tag_is_reopened_as_it_was() -> None:
    """Links keep their href across a cut."""
    text = '<a href="https://x.test/">' + "a" * 5 + "\n" + "b" * 5 + "</a>"

    parts = split_html(text, limit=6)

    assert parts[1].startswith('<a href="https://x.test/">')
    assert parts[0].endswith("</a>")


def test_a_line_longer_than_the_limit_is_hard_cut() -> None:
    """No part exceeds the limit even without line breaks."""
    parts = split_html("a" * 25, limit=10)

    assert [len(part) for part in parts] == [10, 10, 5]


def test_truncate_reports_whether_it_cut() -> None:
    """The mail screen uses this to decide on Show full."""
    short, cut_short = truncate_html("abc", 10)
    long, cut_long = truncate_html("a" * 30, 10)

    assert (short, cut_short) == ("abc", False)
    assert (len(long), cut_long) == (10, True)


@given(st.text(alphabet=st.sampled_from(list("ab \n&<>")), max_size=300))
def test_every_part_fits_for_any_escaped_text(raw: str) -> None:
    """Property: parts of escaped text never exceed the limit."""
    parts = split_html(f"<i>{escape(raw)}</i>", limit=20)

    assert all(visible_length(part) <= 20 for part in parts)


def test_shorten_adds_an_ellipsis_and_joins_whitespace() -> None:
    """Button labels are single line and bounded."""
    assert shorten("a  b\nc", 10) == "a b c"
    assert shorten("abcdefghij", 5) == "abcd…"
