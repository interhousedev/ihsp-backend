"""Proofs, help responses, guest-link tokens and the reduced helper view (§7, §10)."""

import ipaddress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.domain.errors import InvalidProofUrlError
from app.modules.admission.domain.workflow import GuestLink
from app.shared.ids import hash_token, random_token

ProofKind = Literal["linkedin", "telegram", "website", "file", "self_provided"]
ProofStatus = Literal["pending", "checked", "unverifiable", "failed"]

PROOF_URL_MAX: Final = 2000
GUEST_TOKEN_PREFIX: Final = "gst_"
GUEST_SESSION_PREFIX: Final = "gss_"
TOKEN_PREFIX_LEN: Final = 8
_BLOCKED_SUFFIXES: Final = (".internal", ".local", ".localhost", ".lan", ".home")
_LINKEDIN: Final = ("linkedin.com",)
_TELEGRAM: Final = ("t.me", "telegram.me", "telegram.dog")


def _on(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def validate_proof_url(url: str) -> str:
    """Return the url when it is a public https url on port 443, else raise."""
    text = url.strip()
    if not text or len(text) > PROOF_URL_MAX:
        raise InvalidProofUrlError(params={"reason": "length"})
    try:
        parts = urlsplit(text)
        port = parts.port
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise InvalidProofUrlError(params={"reason": "malformed"}) from exc
    if parts.scheme != "https" or parts.username or parts.password:
        raise InvalidProofUrlError(params={"reason": "scheme"})
    if port not in (None, 443):
        raise InvalidProofUrlError(params={"reason": "port"})
    _check_host(host)
    return text


def _check_host(host: str) -> None:
    """Raise unless the host is a public DNS name."""
    if (
        not host
        or "." not in host
        or host == "localhost"
        or host.endswith(_BLOCKED_SUFFIXES)
    ):
        raise InvalidProofUrlError(params={"reason": "host"})
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return
    raise InvalidProofUrlError(params={"reason": "ip_literal"})


def detect_url_kind(url: str) -> ProofKind:
    """Return linkedin, telegram or website from the host of a valid url."""
    host = (urlsplit(url).hostname or "").lower()
    if _on(host, _LINKEDIN):
        return "linkedin"
    if _on(host, _TELEGRAM):
        return "telegram"
    return "website"


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A new token: shown once, only the hash and the prefix are stored."""

    token: str
    token_hash: str
    prefix: str


def issue_token(marker: str = GUEST_TOKEN_PREFIX) -> IssuedToken:
    """Return a random `marker`+43-char token with its stored hash and prefix."""
    token = marker + random_token(32)
    return IssuedToken(token, hash_token(token), token[:TOKEN_PREFIX_LEN])


def token_hash(token: str) -> str:
    """Return the stored hash of a presented token."""
    return hash_token(token)


@dataclass(frozen=True, slots=True)
class Proof:
    """Evidence for an item."""

    id: UUID
    item_id: UUID
    kind: ProofKind
    status: ProofStatus
    url: str | None = None
    file_id: UUID | None = None
    text_sha256: str | None = None
    extraction: str | None = None
    fetched_at: datetime | None = None
    next_check_at: datetime | None = None
    lock_version: int = 0


@dataclass(frozen=True, slots=True)
class HelpResponse:
    """A response of a helper (account or guest) to a request."""

    id: UUID
    help_request_id: UUID
    text: str
    created_at: datetime
    author_user_id: UUID | None = None
    guest_link_id: UUID | None = None
    url: str | None = None
    file_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class GuestLinkRecord:
    """A guest link with the fields the student's list shows."""

    link: GuestLink
    label: str | None
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_reason: str | None = None
    rotated_from: UUID | None = None
    claimed_by: UUID | None = None


@dataclass(frozen=True, slots=True)
class MetricView:
    """A current metric of an item."""

    label: str
    value: str
    unit: str | None


@dataclass(frozen=True, slots=True)
class HelperActivity:
    """What a helper sees of an activity (D1): no private notes, no projections."""

    position: str
    org: str
    description: str
    kind: str
    current_metrics: tuple[MetricView, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class HelperDirectoryEntry:
    """An opted-in helper in the directory: id and display name only."""

    user_id: UUID
    display_name: str
