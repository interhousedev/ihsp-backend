"""DMARC (RFC 7489): record parsing and the pass/fail decision. No I/O here."""

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

# Public suffixes with two labels that matter for our users; everything else uses
# the plain "last two labels" rule of the plan.
_TWO_LABEL_SUFFIXES = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "com.au",
        "co.jp",
        "com.uz",
        "edu.uz",
        "gov.uz",
        "org.uz",
        "net.uz",
        "co.uz",
        "com.tr",
        "com.ru",
    }
)

DmarcOutcome = Literal["pass", "fail", "none"]


class DmarcPolicy(StrEnum):
    """What the domain owner asks receivers to do with failing mail."""

    NONE = "none"
    QUARANTINE = "quarantine"
    REJECT = "reject"


class Alignment(StrEnum):
    """Relaxed (same organizational domain) or strict (same domain)."""

    RELAXED = "r"
    STRICT = "s"


@dataclass(frozen=True, slots=True)
class DmarcRecord:
    """The tags of a ``_dmarc`` TXT record that matter for evaluation."""

    policy: DmarcPolicy
    subdomain_policy: DmarcPolicy | None = None
    adkim: Alignment = Alignment.RELAXED
    aspf: Alignment = Alignment.RELAXED


@dataclass(frozen=True, slots=True)
class DmarcResult:
    """Result of the DMARC evaluation and the policy that applies."""

    result: DmarcOutcome
    policy: DmarcPolicy | None = None


def organizational_domain(domain: str) -> str:
    """Return the organizational domain: the last two labels (see the suffix list)."""
    labels = domain.lower().strip(".").split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    if ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def aligned(first: str, second: str, mode: Alignment) -> bool:
    """Return True if two domains are aligned in the given mode."""
    left, right = first.lower().strip("."), second.lower().strip(".")
    if mode == Alignment.STRICT:
        return left == right
    return organizational_domain(left) == organizational_domain(right)


def _parse_tags(text: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for part in text.split(";"):
        key, separator, value = part.partition("=")
        if separator:
            tags.setdefault(key.strip().lower(), value.strip())
    return tags


def _policy(value: str | None) -> DmarcPolicy | None:
    try:
        return DmarcPolicy(value.lower()) if value else None
    except ValueError:
        return None


def _alignment(value: str | None) -> Alignment:
    return Alignment.STRICT if value and value.lower() == "s" else Alignment.RELAXED


def parse_dmarc_record(text: str) -> DmarcRecord | None:
    """Parse a TXT value; None when it is not a valid ``v=DMARC1`` record."""
    stripped = text.strip()
    if not stripped.lower().startswith("v=dmarc1"):
        return None
    tags = _parse_tags(stripped)
    policy = _policy(tags.get("p"))
    if tags.get("v", "").upper() != "DMARC1" or policy is None:
        return None
    return DmarcRecord(
        policy=policy,
        subdomain_policy=_policy(tags.get("sp")),
        adkim=_alignment(tags.get("adkim")),
        aspf=_alignment(tags.get("aspf")),
    )


def select_record(
    texts: Collection[str], *, at_organizational_domain: bool
) -> DmarcRecord | None:
    """Pick the one valid record among the TXT values (two or more: none apply).

    When the record was found at the organizational domain for a subdomain
    sender, the ``sp`` tag (if any) replaces ``p``.
    """
    records = [rec for rec in map(parse_dmarc_record, texts) if rec is not None]
    if len(records) != 1:
        return None
    record = records[0]
    if at_organizational_domain and record.subdomain_policy is not None:
        return DmarcRecord(
            policy=record.subdomain_policy,
            subdomain_policy=record.subdomain_policy,
            adkim=record.adkim,
            aspf=record.aspf,
        )
    return record


def evaluate_dmarc(
    record: DmarcRecord | None,
    *,
    from_domain: str,
    spf_pass_domain: str | None,
    dkim_pass_domains: Collection[str],
) -> DmarcResult:
    """Pass when SPF or DKIM passed with a domain aligned to the From domain.

    ``spf_pass_domain`` is the MAIL FROM (or HELO) domain when SPF passed, else
    None; ``dkim_pass_domains`` are the ``d=`` domains of verified signatures.
    """
    if record is None:
        return DmarcResult(result="none")
    spf_ok = spf_pass_domain is not None and aligned(
        spf_pass_domain, from_domain, record.aspf
    )
    dkim_ok = any(aligned(d, from_domain, record.adkim) for d in dkim_pass_domains)
    return DmarcResult(
        result="pass" if spf_ok or dkim_ok else "fail", policy=record.policy
    )
