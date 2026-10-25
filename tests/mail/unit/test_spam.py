"""MAIL-5, MAIL-9: the spam score."""

from app.modules.mail.domain.checks import InboundChecks
from app.modules.mail.domain.spam import SPAM_THRESHOLD, SpamVerdict, spam_verdict


def verdict(
    checks: InboundChecks | None = None,
    *,
    message_id: bool = True,
    empty: bool = False,
) -> SpamVerdict:
    """Score a message with the given checks."""
    return spam_verdict(
        checks or InboundChecks(), has_message_id=message_id, is_empty=empty
    )


def test_a_clean_message_scores_zero() -> None:
    """MAIL-9: nothing wrong -> 0."""
    result = verdict()

    assert result.score == 0
    assert not result.is_spam


def test_spf_fail_alone_is_not_spam() -> None:
    """MAIL-9: SPF fail adds 3."""
    result = verdict(InboundChecks(spf="fail"))

    assert result.score == 3
    assert result.reasons == ("spf-fail",)
    assert not result.is_spam


def test_softfail_and_temperror_do_not_count() -> None:
    """MAIL-9: only a hard SPF fail scores."""
    assert verdict(InboundChecks(spf="softfail")).score == 0
    assert verdict(InboundChecks(spf="temperror")).score == 0


def test_dkim_not_verified_under_an_enforcing_dmarc_adds_three() -> None:
    """MAIL-9: DKIM fail with DMARC reject/quarantine adds 3."""
    for policy in ("reject", "quarantine"):
        checks = InboundChecks(dkim="fail", dmarc="fail", dmarc_policy=policy)
        assert verdict(checks).score == 3


def test_dkim_fail_under_a_relaxed_dmarc_policy_does_not_score() -> None:
    """MAIL-9: p=none is only monitoring."""
    checks = InboundChecks(dkim="fail", dmarc="fail", dmarc_policy="none")

    assert verdict(checks).score == 0


def test_dmarc_passed_by_spf_makes_a_bad_dkim_signature_harmless() -> None:
    """MAIL-9: alignment through SPF is enough."""
    checks = InboundChecks(dkim="fail", dmarc="pass", dmarc_policy="reject")

    assert verdict(checks).score == 0


def test_missing_message_id_and_empty_content_add_two_each() -> None:
    """MAIL-9: no Message-ID +2, empty subject and body +2."""
    assert verdict(message_id=False).score == 2
    assert verdict(empty=True).score == 2
    assert verdict(message_id=False, empty=True).score == 4


def test_spam_starts_at_five() -> None:
    """MAIL-5: threshold 5."""
    assert SPAM_THRESHOLD == 5
    assert verdict(InboundChecks(spf="fail"), message_id=False).is_spam
    assert not verdict(message_id=False, empty=True).is_spam
    both = InboundChecks(spf="fail", dkim="fail", dmarc="fail", dmarc_policy="reject")
    result = verdict(both)
    assert result.score == 6
    assert result.is_spam
