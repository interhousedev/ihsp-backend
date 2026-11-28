"""A visitor's message to a club: validated, relayed to the owner, never stored."""

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.activities.domain.errors import (
    BadRequest,
    Conflict,
    Invalid,
    Missing,
)

__all__ = [
    "MAX_BODY",
    "CaptchaFailedError",
    "ContactInvalidError",
    "ContactNotAcceptedError",
    "ContactRequest",
    "ContactUnavailableError",
    "accepts",
    "hash_ip",
]

MAX_BODY = 2000
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]*>")


class ContactInvalidError(Invalid):
    """A contact field is invalid."""


class ContactNotAcceptedError(Missing):
    """The club takes no public messages."""


class ContactUnavailableError(Conflict):
    """The club owner cannot be reached on Telegram."""


class CaptchaFailedError(BadRequest):
    """The captcha check failed."""


def accepts(club: Any) -> bool:
    """A club takes messages when active, public and switched on."""
    return (
        str(club.status) == "active" and club.visibility_public and club.contact_enabled
    )


def hash_ip(ip: str, salt: str) -> str:
    """Salted hash used only as a rate-limit key; the raw address is never kept."""
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


def _plain(text: str) -> str:
    return _TAG.sub("", _SCRIPT.sub("", text)).strip()


@dataclass(frozen=True, slots=True)
class ContactRequest:
    """A checked message on its way to the club owner's Telegram."""

    club_id: UUID
    name: str
    email: str
    body: str
    ip_hash: str
    is_spam: bool

    @classmethod
    def create(
        cls,
        *,
        club: Any,
        name: str,
        email: str,
        body: str,
        ip: str,
        salt: str,
        honeypot: str,
    ) -> "ContactRequest":
        """Validate and build; a filled honeypot marks it spam (silently dropped)."""
        if not accepts(club):
            raise ContactNotAcceptedError()
        plain, who = _plain(body), name.strip()
        if honeypot:
            plain, who = plain[:MAX_BODY], who[:100]
        else:
            if not plain or len(body) > MAX_BODY:
                raise ContactInvalidError(params={"field": "body"})
            if not who or len(who) > 100:
                raise ContactInvalidError(params={"field": "name"})
            if not _EMAIL.fullmatch(email.strip()):
                raise ContactInvalidError(params={"field": "email"})
        return cls(
            club.id, who, email.strip(), plain, hash_ip(ip, salt), bool(honeypot)
        )
