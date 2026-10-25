"""One spelling per web page: the rules behind stored pages and notebook sources."""

from app.shared.web_urls import normalise_web_url

import pytest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.ORG/Lesson#part", "https://example.org/Lesson"),
        ("https://example.org", "https://example.org/"),
        ("https://example.org:443/a?x=1&y=2#top", "https://example.org/a?x=1&y=2"),
        ("http://example.org:8080/a", "http://example.org:8080/a"),
        ("https://[::1]:8443/x", "https://[::1]:8443/x"),
        ("  https://example.org/a  ", "https://example.org/a"),
    ],
)
def test_the_same_page_has_one_spelling(raw: str, expected: str) -> None:
    assert normalise_web_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://example.org/file",
        "javascript:alert(1)",
        "https://user:pass@example.org/",
        "https://:443/",
        "https://example.org:notaport/",
        "",
    ],
)
def test_only_web_addresses_with_a_host_are_kept(raw: str) -> None:
    assert normalise_web_url(raw) is None
