"""Prompt injection: third-party text is cleaned and labelled, never obeyed."""

from app.interfaces.mcp.untrusted import clean_text, mark_untrusted, safe_external_url

import pytest


def test_clean_text_strips_control_and_invisible_characters() -> None:
    """Hidden instructions in zero-width, bidi and tag characters do not survive."""
    hidden = "a​b‮c\x07d\U000e0041e﻿"

    assert clean_text(hidden) == "abcde"


def test_clean_text_keeps_lines_and_every_school_alphabet() -> None:
    """Content is not rewritten: new lines, Cyrillic and ʼ stay."""
    text = "Oʻquvchi\nУрок\tLesson"

    assert clean_text(text) == text


def test_clean_text_caps_the_length() -> None:
    """Bounded output."""
    assert clean_text("abcdef", max_length=3) == "abc…"


def test_mark_untrusted_cleans_named_fields_and_lists_them() -> None:
    """The client sees which fields hold other people's text."""
    result = mark_untrusted(
        {"id": "1​", "topic": "x​y", "rows": [{"text": "a​b", "n": 1}]},
        "topic",
        "rows[].text",
    )

    assert result == {
        "id": "1​",
        "topic": "xy",
        "rows": [{"text": "ab", "n": 1}],
        "untrusted_fields": ["topic", "rows[].text"],
    }


def test_mark_untrusted_ignores_absent_and_null_fields() -> None:
    """Optional text may be missing."""
    assert mark_untrusted({"topic": None}, "topic", "other", "rows[].text") == {
        "topic": None,
        "untrusted_fields": ["topic", "other", "rows[].text"],
    }


def test_mark_untrusted_does_not_change_its_input() -> None:
    """Views may be shared."""
    original = {"rows": [{"text": "a​b"}]}

    mark_untrusted(original, "rows[].text")

    assert original == {"rows": [{"text": "a​b"}]}


@pytest.mark.parametrize(
    "url",
    ["https://example.org/a", "http://example.org", "HTTPS://EXAMPLE.org/x?y=1"],
)
def test_web_addresses_are_allowed(url: str) -> None:
    """External links from content stay available."""
    assert safe_external_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "file:///etc/passwd",
        "//example.org",
        "https://",
        "https://user:pass@example.org",
        "https://exa\nmple.org",
        "",
        None,
    ],
)
def test_other_addresses_are_dropped(url: str | None) -> None:
    """Only http(s) with a host, no credentials and no control characters."""
    assert safe_external_url(url) is None
