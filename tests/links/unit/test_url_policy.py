"""SL-4, SL-8: URL safety, blocklist and the interstitial allowlist."""

from app.modules.links.domain.errors import BlockedUrlError
from app.modules.links.domain.url_policy import UrlPolicy, is_public_ip

import pytest

POLICY = UrlPolicy(frozenset({"blocked.example"}))


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "ftp://example.org/file",
        "file:///etc/passwd",
        "data:text/html,<script>",
        "https://",
        "//example.org/x",
        "https://user:secret@example.org/",
        "https://user@example.org/",
        "https://blocked.example/path",
        "https://sub.blocked.example/path",
        "https://BLOCKED.example./path",
        "https://example.org/" + "a" * 2100,
        "https://exa mple.org/",
        "https://example.org:notaport/",
        "",
    ],
)
def test_unsafe_urls_are_refused(url: str) -> None:
    """SL-8: only plain http(s) URLs to unblocked hosts are allowed."""
    with pytest.raises(BlockedUrlError) as error:
        POLICY.check(url)

    assert error.value.status == 422
    assert error.value.code == "links/blocked-url"


def test_valid_url_is_returned_with_its_host() -> None:
    """SL-1: a normal URL passes."""
    checked = POLICY.check("  https://Khanacademy.org/math?x=1  ")

    assert checked.url == "https://Khanacademy.org/math?x=1"
    assert checked.host == "khanacademy.org"


def test_similar_domain_is_not_blocked() -> None:
    """SL-8: only the domain and its subdomains match, not look-alikes."""
    assert not POLICY.is_blocked("notblocked.example")
    assert POLICY.is_blocked("blocked.example")


@pytest.mark.parametrize(
    "url",
    [
        "https://ihsu.uz/r/102",
        "https://sp.ihsu.uz/x",
        "https://docs.google.com/document/d/1",
        "https://drive.google.com/file/d/1",
        "https://youtube.com/watch?v=1",
        "https://www.youtube.com/watch?v=1",
        "https://youtu.be/abc",
        "https://en.wikipedia.org/wiki/Physics",
        "https://khanacademy.org/",
        "https://stepik.org/course/1",
    ],
)
def test_allowlisted_hosts_skip_the_interstitial(url: str) -> None:
    """SL-4: trusted domains redirect directly."""
    assert not POLICY.needs_interstitial(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/",
        "https://ihsu.uz.evil.example/",
        "https://evilihsu.uz/",
        "https://youtube.com.evil.example/",
        "https://example.org/?next=https://ihsu.uz/",
    ],
)
def test_other_hosts_need_the_interstitial(url: str) -> None:
    """SL-4: look-alike hosts are not trusted."""
    assert POLICY.needs_interstitial(url)


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("192.168.0.5", False),
        ("169.254.169.254", False),
        ("::1", False),
        ("not-an-ip", False),
    ],
)
def test_only_global_addresses_count_as_public(address: str, public: bool) -> None:
    """SL-8: the title fetcher must not reach internal hosts."""
    assert is_public_ip(address) is public
