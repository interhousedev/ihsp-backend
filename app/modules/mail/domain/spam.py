"""Spam score of an inbound message (MAIL-9)."""

from dataclasses import dataclass

from app.modules.mail.domain.checks import InboundChecks

SPAM_THRESHOLD = 5.0
SPF_FAIL_POINTS = 3.0
DKIM_DMARC_POINTS = 3.0
NO_MESSAGE_ID_POINTS = 2.0
EMPTY_MESSAGE_POINTS = 2.0

_ENFORCED_POLICIES = frozenset({"quarantine", "reject"})


@dataclass(frozen=True, slots=True)
class SpamVerdict:
    """The score, the reasons that added to it and the decision."""

    score: float
    reasons: tuple[str, ...]

    @property
    def is_spam(self) -> bool:
        """Spam when the score reaches the threshold."""
        return self.score >= SPAM_THRESHOLD


def spam_verdict(
    checks: InboundChecks, *, has_message_id: bool, is_empty: bool
) -> SpamVerdict:
    """Add up the points: SPF fail, DKIM not verified under an enforcing DMARC."""
    score = 0.0
    reasons: list[str] = []
    if checks.spf == "fail":
        score += SPF_FAIL_POINTS
        reasons.append("spf-fail")
    dmarc_enforced = (
        checks.dmarc == "fail" and checks.dmarc_policy in _ENFORCED_POLICIES
    )
    if dmarc_enforced and checks.dkim != "pass":
        score += DKIM_DMARC_POINTS
        reasons.append("dkim-fail-dmarc")
    if not has_message_id:
        score += NO_MESSAGE_ID_POINTS
        reasons.append("no-message-id")
    if is_empty:
        score += EMPTY_MESSAGE_POINTS
        reasons.append("empty-message")
    return SpamVerdict(score=score, reasons=tuple(reasons))
