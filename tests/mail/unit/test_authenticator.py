"""MAIL-9: SPF, DKIM and DMARC checks of inbound mail (stubbed DNS, real signatures)."""

import base64
import time
from collections.abc import Callable

from app.modules.mail.domain.checks import InboundChecks
from app.modules.mail.infrastructure.auth.authenticator import DnsInboundAuthenticator
from tests.mail.fakes import FakeTxtResolver
from tests.mail.helpers import make_raw

import dkim
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Real top-level domains: with ".test" the organizational domain would be wrong.
SIGNER = "example.com"
DMARC_REJECT = "v=DMARC1; p=reject"


@pytest.fixture(scope="module")
def key() -> tuple[bytes, bytes]:
    """An RSA key pair: private PEM and the DKIM TXT record of the public key."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    der = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return pem, b"v=DKIM1; k=rsa; p=" + base64.b64encode(der)


def signed(raw: bytes, pem: bytes, domain: str = SIGNER) -> bytes:
    """Prepend a DKIM-Signature made for ``domain``."""
    header = dkim.sign(
        raw,
        b"sel",
        domain.encode(),
        pem,
        include_headers=[b"from", b"to", b"subject", b"message-id", b"date"],
    )
    return bytes(header) + raw


def dns_for(txt: bytes) -> Callable[..., bytes | None]:
    """A dkimpy dnsfunc that knows the selector record of both test domains."""

    def lookup(name: bytes, timeout: int = 5) -> bytes | None:
        known = {b"sel._domainkey.example.com.", b"sel._domainkey.other.org."}
        return txt if name in known else None

    return lookup


def spf_returning(result: str) -> Callable[[str, str, str], str]:
    def check(peer_ip: str, sender: str, helo: str) -> str:
        return result

    return check


def authenticator(
    resolver: FakeTxtResolver,
    txt: bytes = b"",
    *,
    spf: str = "none",
    enable_spf: bool = True,
    enable_dkim: bool = True,
    timeout: float = 5.0,
) -> DnsInboundAuthenticator:
    return DnsInboundAuthenticator(
        resolver,
        enable_spf=enable_spf,
        enable_dkim=enable_dkim,
        spf_function=spf_returning(spf),
        dkim_dnsfunc=dns_for(txt),
        timeout=timeout,
    )


async def run(
    auth: DnsInboundAuthenticator, raw: bytes, mail_from: str = "anna@example.com"
) -> InboundChecks:
    """Run the checks for a message from 203.0.113.9."""
    return await auth.check(
        raw, peer_ip="203.0.113.9", mail_from=mail_from, helo="mx.example.com"
    )


async def test_a_signed_message_aligned_with_from_passes_dmarc(
    key: tuple[bytes, bytes],
) -> None:
    """MAIL-9: DKIM pass with d=example.com for From: example.com -> dmarc pass."""
    pem, txt = key
    raw = signed(make_raw(sender="Anna <anna@example.com>"), pem)
    resolver = FakeTxtResolver({"_dmarc.example.com": [DMARC_REJECT]})

    checks = await run(authenticator(resolver, txt, spf="fail"), raw)

    assert checks.dkim == "pass"
    assert checks.dkim_domains == ("example.com",)
    assert checks.spf == "fail"
    assert (checks.dmarc, checks.dmarc_policy) == ("pass", "reject")


async def test_an_unsigned_message_has_no_dkim_result_and_fails_dmarc_without_spf(
    key: tuple[bytes, bytes],
) -> None:
    """MAIL-9: dkim=none, spf fail -> dmarc fail under p=reject."""
    _, txt = key
    resolver = FakeTxtResolver({"_dmarc.example.com": [DMARC_REJECT]})

    checks = await run(authenticator(resolver, txt, spf="fail"), make_raw())

    assert checks.dkim == "none"
    assert (checks.dmarc, checks.dmarc_policy) == ("fail", "reject")


async def test_a_tampered_body_fails_dkim(key: tuple[bytes, bytes]) -> None:
    """MAIL-9: the signature no longer matches."""
    pem, txt = key
    raw = signed(make_raw(body="original"), pem).replace(b"original", b"changed!")
    resolver = FakeTxtResolver({"_dmarc.example.com": [DMARC_REJECT]})

    checks = await run(authenticator(resolver, txt), raw)

    assert checks.dkim == "fail"
    assert checks.dkim_domains == ()
    assert checks.dmarc == "fail"


async def test_a_signature_of_another_domain_fails_alignment(
    key: tuple[bytes, bytes],
) -> None:
    """MAIL-9: valid signature for example.com, but From is evil.com."""
    pem, txt = key
    raw = signed(make_raw(sender="CEO <ceo@evil.com>"), pem, "example.com")
    resolver = FakeTxtResolver({"_dmarc.evil.com": [DMARC_REJECT]})

    checks = await run(authenticator(resolver, txt), raw, mail_from="ceo@evil.com")

    assert checks.dkim == "pass"
    assert checks.dmarc == "fail"
    assert checks.from_domain == "evil.com"


async def test_spf_pass_aligned_with_from_passes_dmarc_without_a_signature() -> None:
    """MAIL-9: SPF alignment (relaxed) is enough."""
    resolver = FakeTxtResolver({"_dmarc.example.com": [DMARC_REJECT]})

    checks = await run(
        authenticator(resolver, spf="pass"),
        make_raw(sender="anna@example.com"),
        mail_from="bounce@mail.example.com",
    )

    assert checks.spf == "pass"
    assert checks.spf_domain == "mail.example.com"
    assert checks.dmarc == "pass"


async def test_spf_pass_for_another_domain_does_not_align() -> None:
    """MAIL-9: SPF passes for the sender's host, not for the From domain."""
    resolver = FakeTxtResolver({"_dmarc.example.com": [DMARC_REJECT]})

    checks = await run(
        authenticator(resolver, spf="pass"),
        make_raw(sender="anna@example.com"),
        mail_from="bounce@other.org",
    )

    assert checks.dmarc == "fail"


async def test_a_null_sender_checks_spf_for_the_helo_domain() -> None:
    """MAIL-9: bounces (MAIL FROM:<>) use postmaster@HELO."""
    seen: list[str] = []

    def spf(peer_ip: str, sender: str, helo: str) -> str:
        seen.append(sender)
        return "pass"

    auth = DnsInboundAuthenticator(
        FakeTxtResolver(), enable_spf=True, enable_dkim=False, spf_function=spf
    )

    checks = await run(auth, make_raw(), mail_from="")

    assert seen == ["postmaster@mx.example.com"]
    assert checks.spf_domain == "mx.example.com"


async def test_the_record_of_the_organizational_domain_is_used_for_subdomains() -> None:
    """MAIL-9: _dmarc.news.example.com, then _dmarc.example.com."""
    resolver = FakeTxtResolver({"_dmarc.example.com": ["v=DMARC1; p=quarantine"]})

    checks = await run(
        authenticator(resolver),
        make_raw(sender="news@news.example.com"),
        mail_from="news@news.example.com",
    )

    assert resolver.queries == ["_dmarc.news.example.com", "_dmarc.example.com"]
    assert checks.dmarc_policy == "quarantine"


async def test_a_domain_without_a_record_has_dmarc_none() -> None:
    """MAIL-9: no DMARC record -> none."""
    checks = await run(authenticator(FakeTxtResolver()), make_raw())

    assert (checks.dmarc, checks.dmarc_policy) == ("none", None)


async def test_a_dns_failure_leaves_dmarc_unknown_not_failed() -> None:
    """MAIL-9: a timeout is never a fail."""
    resolver = FakeTxtResolver()
    resolver.failing.add("_dmarc.example.com")

    checks = await run(authenticator(resolver, spf="fail"), make_raw())

    assert checks.dmarc == "none"
    assert checks.spf == "fail"


async def test_disabled_checks_are_not_run() -> None:
    """MAIL-9: both toggles off -> nothing runs, nothing is looked up."""
    resolver = FakeTxtResolver({"_dmarc.example.com": [DMARC_REJECT]})
    auth = authenticator(resolver, enable_spf=False, enable_dkim=False, spf="fail")

    checks = await run(auth, make_raw())

    assert (checks.spf, checks.dkim, checks.dmarc) == ("none", "none", "none")
    assert resolver.queries == []


async def test_dmarc_needs_both_spf_and_dkim() -> None:
    """MAIL-9: with only SPF enabled DMARC is not evaluated."""
    resolver = FakeTxtResolver({"_dmarc.example.com": [DMARC_REJECT]})

    checks = await run(
        authenticator(resolver, enable_dkim=False, spf="fail"), make_raw()
    )

    assert checks.spf == "fail"
    assert checks.dmarc == "none"
    assert resolver.queries == []


async def test_a_slow_check_gives_a_temporary_error() -> None:
    """MAIL-9: the SMTP client is not kept waiting for a dead DNS server."""

    def slow(peer_ip: str, sender: str, helo: str) -> str:
        time.sleep(0.3)
        return "pass"

    auth = DnsInboundAuthenticator(
        FakeTxtResolver(),
        enable_spf=True,
        enable_dkim=False,
        spf_function=slow,
        timeout=0.05,
    )

    checks = await run(auth, make_raw())

    assert checks.spf == "temperror"
