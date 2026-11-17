"""Proofs of items: URL validation and the proof record (§7)."""

import ipaddress
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.domain.errors import InvalidProofUrlError

ProofKind = Literal["linkedin", "telegram", "website", "file", "self_provided"]
ProofStatus = Literal["pending", "checked", "unverifiable", "failed"]

PROOF_URL_MAX: Final = 2000
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
