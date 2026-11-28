"""A student's own find: a plan entry that is not in the catalog.

Titles, links and dates come from the student or from an AI assistant they use, so
they are stored as data: the link is checked as text and never fetched, and the
entry is shown as "not verified by the school". Pure.
"""

import datetime as dt
import hashlib
import ipaddress
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.admission.domain.opportunities import (
    KINDS,
    REASON_MAX,
    SUMMARY_MAX,
    TERMS,
    TEXT_MAX,
    TITLE_MAX,
    OpportunityKind,
)
from app.shared.base_error import ConflictError


class PlanDuplicateError(ConflictError):
    """The student already has this find in the plan (same dedup key)."""

    code = "admission/plan_duplicate"
    message_key = "plan-duplicate"


PersonalOrigin = Literal["web", "mcp"]
ORIGINS: Final = ("web", "mcp")
URL_MAX: Final = 2000
PERSONAL_ADD_LIMIT: Final = 20
"""Entries a student may add per day (spam guard)."""
EARLIEST: Final = dt.date(2000, 1, 1)
LATEST: Final = dt.date(2100, 12, 31)
_URL_FORBIDDEN: Final = frozenset("\"'()<>\\`")
_TLD: Final = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
_MULTILINE: Final = frozenset("\n\t")


@dataclass(frozen=True, slots=True)
class PersonalEntry:
    """A saved personal entry; `submission_id` is set once it was proposed."""

    id: UUID
    student_id: UUID
    kind: OpportunityKind
    title: str
    provider: str | None
    url: str | None
    summary: str | None
    registration_deadline: dt.date | None
    starts_on: dt.date | None
    ends_on: dt.date | None
    planned_grade: int | None
    planned_term: str | None
    note: str | None
    origin: PersonalOrigin
    dedup_key: str
    created_at: dt.datetime
    updated_at: dt.datetime
    submission_id: UUID | None = None
    lock_version: int = 0

    @property
    def dates(self) -> tuple[tuple[str, dt.date], ...]:
        """Dated events as `(kind, day)`, kinds as in the catalog calendar."""
        out = [
            ("registration", self.registration_deadline),
            ("start", self.starts_on),
            ("end", self.ends_on),
        ]
        return tuple((k, d) for k, d in out if d is not None)


@dataclass(frozen=True, slots=True)
class PersonalDraft:
    """The fields of an entry as typed or sent by an assistant."""

    kind: str
    title: str
    provider: str | None = None
    url: str | None = None
    summary: str | None = None
    registration_deadline: dt.date | None = None
    starts_on: dt.date | None = None
    ends_on: dt.date | None = None
    planned_grade: int | None = None
    planned_term: str | None = None
    note: str | None = None

    def problems(self) -> list[str]:  # noqa: C901 - one check per field
        """Names of the invalid fields, in a stable order."""
        bad: list[str] = []
        if self.kind not in KINDS:
            bad.append("kind")
        if not _line(self.title, TITLE_MAX, required=True):
            bad.append("title")
        if self.provider is not None and not _line(self.provider, TEXT_MAX):
            bad.append("provider")
        if self.url is not None and not is_safe_url(self.url):
            bad.append("url")
        if self.summary is not None and not _text(self.summary, SUMMARY_MAX):
            bad.append("summary")
        days = (self.registration_deadline, self.starts_on, self.ends_on)
        if any(d is not None and not EARLIEST <= d <= LATEST for d in days):
            bad.append("dates")
        elif self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            bad.append("ends_on")
        if self.planned_term is not None and self.planned_term not in TERMS:
            bad.append("planned_term")
        if self.note is not None and not _text(self.note, REASON_MAX):
            bad.append("note")
        return bad


def _clean(text: str, *, keep: frozenset[str] = frozenset()) -> bool:
    return all(ch in keep or unicodedata.category(ch)[0] != "C" for ch in text)


def _line(text: str, limit: int, *, required: bool = False) -> bool:
    """One printable line of at most `limit` characters."""
    value = text.strip()
    if required and not value:
        return False
    return len(value) <= limit and _clean(value)


def _text(text: str, limit: int) -> bool:
    """Printable text (newlines and tabs allowed) of at most `limit` characters."""
    return len(text.strip()) <= limit and _clean(text.strip(), keep=_MULTILINE)


def is_safe_url(value: str) -> bool:  # noqa: C901 - one rule per URL part
    """A plain `https` link as text: no credentials, no IP literal, no controls.

    The server never opens it; this only keeps hostile or private-network
    addresses out of the page.
    """
    if not value or len(value) > URL_MAX:
        return False
    if any(c in _URL_FORBIDDEN or c.isspace() or not c.isprintable() for c in value):
        return False
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return False
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return False
    if port not in (None, 443):
        return False
    if _is_ip(host):
        return False
    labels = host.split(".")
    return len(labels) >= 2 and bool(_TLD.match(labels[-1]))


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def dedup_key(keys: Iterable[str]) -> str:
    """A 64-character digest of a set of normalised dedup keys (order-free)."""
    joined = "\n".join(sorted(set(keys)))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
