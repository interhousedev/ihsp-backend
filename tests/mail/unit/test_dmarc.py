"""MAIL-9: DMARC record parsing, alignment and the pass/fail decision."""

from app.modules.mail.domain.dmarc import (
    Alignment,
    DmarcPolicy,
    aligned,
    evaluate_dmarc,
    organizational_domain,
    parse_dmarc_record,
    select_record,
)

import pytest


def test_a_record_is_parsed_with_policy_and_alignment_modes() -> None:
    """MAIL-9: p, sp, adkim and aspf are read."""
    record = parse_dmarc_record("v=DMARC1; p=Reject; sp=none; adkim=s; aspf=r; pct=100")

    assert record is not None
    assert record.policy == DmarcPolicy.REJECT
    assert record.subdomain_policy == DmarcPolicy.NONE
    assert record.adkim == Alignment.STRICT
    assert record.aspf == Alignment.RELAXED


@pytest.mark.parametrize(
    "text",
    ["", "v=spf1 -all", "v=DMARC1", "v=DMARC1; p=maybe", "p=reject; v=DMARC1"],
)
def test_invalid_records_are_ignored(text: str) -> None:
    """MAIL-9: no v=DMARC1 first, or no valid p= -> no policy."""
    assert parse_dmarc_record(text) is None


def test_alignment_defaults_to_relaxed() -> None:
    """MAIL-9: adkim and aspf default to r."""
    record = parse_dmarc_record("v=DMARC1; p=quarantine")

    assert record is not None
    assert (record.adkim, record.aspf) == (Alignment.RELAXED, Alignment.RELAXED)


def test_two_records_cancel_each_other() -> None:
    """RFC 7489: more than one valid record means there is no policy."""
    texts = ["v=DMARC1; p=reject", "v=DMARC1; p=none", "v=spf1 -all"]

    assert select_record(texts, at_organizational_domain=False) is None


def test_the_subdomain_policy_applies_when_found_at_the_organizational_domain() -> None:
    """MAIL-9: sp= replaces p= for a subdomain sender."""
    record = select_record(
        ["v=DMARC1; p=reject; sp=quarantine"], at_organizational_domain=True
    )

    assert record is not None
    assert record.policy == DmarcPolicy.QUARANTINE


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("example.com", "example.com"),
        ("mail.example.com", "example.com"),
        ("a.b.example.com", "example.com"),
        ("Mail.Example.COM.", "example.com"),
        ("news.example.co.uk", "example.co.uk"),
        ("lyceum.edu.uz", "lyceum.edu.uz"),
        ("com", "com"),
    ],
)
def test_the_organizational_domain_is_the_last_two_labels(
    domain: str, expected: str
) -> None:
    """MAIL-9: last two labels (three under a known two-label suffix)."""
    assert organizational_domain(domain) == expected


def test_relaxed_alignment_accepts_subdomains_and_strict_does_not() -> None:
    """MAIL-9: adkim/aspf r vs s."""
    assert aligned("mail.example.com", "example.com", Alignment.RELAXED)
    assert not aligned("mail.example.com", "example.com", Alignment.STRICT)
    assert aligned("Example.com", "example.com", Alignment.STRICT)
    assert not aligned("evil.com", "example.com", Alignment.RELAXED)


def test_spf_pass_with_an_aligned_domain_passes() -> None:
    """MAIL-9: SPF passed for the From domain."""
    result = evaluate_dmarc(
        parse_dmarc_record("v=DMARC1; p=reject"),
        from_domain="example.com",
        spf_pass_domain="bounce.example.com",
        dkim_pass_domains=[],
    )

    assert (result.result, result.policy) == ("pass", DmarcPolicy.REJECT)


def test_dkim_pass_with_an_aligned_domain_passes() -> None:
    """MAIL-9: a verified d= signature aligned with From."""
    result = evaluate_dmarc(
        parse_dmarc_record("v=DMARC1; p=quarantine"),
        from_domain="example.com",
        spf_pass_domain=None,
        dkim_pass_domains=["example.com"],
    )

    assert result.result == "pass"


def test_passing_checks_for_another_domain_fail_dmarc() -> None:
    """MAIL-9: SPF/DKIM pass but not aligned with the From domain."""
    result = evaluate_dmarc(
        parse_dmarc_record("v=DMARC1; p=reject"),
        from_domain="evil.com",
        spf_pass_domain="example.com",
        dkim_pass_domains=["example.com"],
    )

    assert (result.result, result.policy) == ("fail", DmarcPolicy.REJECT)


def test_strict_dkim_alignment_rejects_a_subdomain_signature() -> None:
    """MAIL-9: adkim=s needs the same domain."""
    result = evaluate_dmarc(
        parse_dmarc_record("v=DMARC1; p=reject; adkim=s"),
        from_domain="example.com",
        spf_pass_domain=None,
        dkim_pass_domains=["mail.example.com"],
    )

    assert result.result == "fail"


def test_no_record_means_none() -> None:
    """MAIL-9: a domain without DMARC has no result and no policy."""
    result = evaluate_dmarc(
        None, from_domain="example.com", spf_pass_domain=None, dkim_pass_domains=[]
    )

    assert (result.result, result.policy) == ("none", None)
