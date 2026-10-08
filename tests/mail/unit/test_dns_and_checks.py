"""MAIL-9: DNS TXT lookups and the SPF/DKIM wrappers (libraries stubbed or offline)."""

import time
from typing import Any

from app.modules.mail.infrastructure.auth.dkim_check import run_dkim, verify_dkim
from app.modules.mail.infrastructure.auth.dns_txt_resolver import DnsTxtResolver
from app.modules.mail.infrastructure.auth.spf_check import check_spf, run_spf
from app.modules.mail.ports.txt_resolver import DnsTemporaryError
from tests.mail.helpers import make_raw

import dns.asyncresolver
import dns.exception
import dns.name
import dns.resolver
import pytest
import spf


class _Rdata:
    def __init__(self, *strings: bytes) -> None:
        self.strings = strings


def _resolving(outcome: Any) -> Any:
    async def resolve(self: Any, name: str, rdtype: str, **kwargs: Any) -> Any:
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return resolve


async def test_txt_strings_of_a_record_are_joined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MAIL-9: long TXT values come in several strings."""
    answer = [_Rdata(b"v=DMARC1; ", b"p=reject"), _Rdata(b"v=spf1 -all")]
    monkeypatch.setattr(
        dns.asyncresolver.Resolver, "resolve", _resolving(answer), raising=True
    )

    assert await DnsTxtResolver().txt("_dmarc.example.com") == [
        "v=DMARC1; p=reject",
        "v=spf1 -all",
    ]


@pytest.mark.parametrize(
    "error",
    [
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.name.EmptyLabel,
        dns.name.LabelTooLong,
    ],
)
async def test_a_missing_record_is_an_empty_list(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    """MAIL-9: no record is not an error."""
    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve", _resolving(error()))

    assert await DnsTxtResolver().txt("_dmarc.example.com") == []


@pytest.mark.parametrize(
    "error", [dns.resolver.LifetimeTimeout, dns.resolver.NoNameservers]
)
async def test_a_timeout_or_server_failure_is_a_temporary_error(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    """MAIL-9: unknown, not 'no policy'."""
    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve", _resolving(error()))

    with pytest.raises(DnsTemporaryError):
        await DnsTxtResolver().txt("_dmarc.example.com")


def test_spf_results_are_lower_case_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    """MAIL-9: whatever pyspf returns, normalized."""
    monkeypatch.setattr(spf, "check2", lambda *a, **k: ("Softfail", "why"))

    assert check_spf("203.0.113.9", "a@example.com", "mx.example.com") == "softfail"


def test_spf_errors_become_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """MAIL-9: temperror and permerror instead of exceptions."""

    def temp(*args: Any, **kwargs: Any) -> Any:
        raise spf.TempError("dns down")

    monkeypatch.setattr(spf, "check2", temp)
    assert check_spf("203.0.113.9", "a@example.com", "h") == "temperror"


def test_a_malformed_peer_address_is_a_permanent_error() -> None:
    """MAIL-9: pyspf raises PermError for a bad IP; no DNS is needed."""
    assert check_spf("not-an-ip", "a@example.com", "h") == "permerror"


async def test_a_slow_spf_lookup_is_a_temporary_error() -> None:
    """MAIL-9: the wait is bounded."""

    def slow(peer_ip: str, sender: str, helo: str) -> str:
        time.sleep(0.2)
        return "pass"

    assert await run_spf(slow, "203.0.113.9", "a@example.com", "h", 0.02) == "temperror"


def test_a_message_without_signature_has_no_dkim_result() -> None:
    """MAIL-9: none, not fail."""
    outcome = verify_dkim(make_raw())

    assert (outcome.result, outcome.domains) == ("none", ())


def test_a_broken_signature_header_fails_without_raising() -> None:
    """MAIL-9: garbage in DKIM-Signature -> fail."""
    raw = b"DKIM-Signature: v=1; this is not valid\r\n" + make_raw()

    assert verify_dkim(raw).result == "fail"


def test_an_unreadable_message_fails_without_raising() -> None:
    """MAIL-9: dkimpy cannot parse it -> fail."""
    assert verify_dkim(b"\x00\x01 no headers at all").result in {"none", "fail"}


async def test_a_slow_dkim_lookup_counts_as_a_failure() -> None:
    """MAIL-9: the wait is bounded."""
    raw = (
        b"DKIM-Signature: v=1; a=rsa-sha256; d=example.com; s=sel; c=relaxed/relaxed;"
        b" h=from; bh=AAAA; b=AAAA\r\n" + make_raw()
    )

    def slow_dns(name: bytes, timeout: int = 5) -> bytes | None:
        time.sleep(0.3)
        return None

    outcome = await run_dkim(raw, slow_dns, 0.05)

    assert outcome.result == "fail"
