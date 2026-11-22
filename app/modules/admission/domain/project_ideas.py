"""Project ideas ("What project can I make?") and the helpers a student may contact."""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal, get_args
from uuid import UUID

from app.shared.base_error import ValidationFailedError

HelpTag = Literal[
    "website_tech",
    "business_growth",
    "pitching",
    "org_outreach",
    "fundraising",
    "product_dev",
]
HelpType = Literal[
    "venue",
    "funding",
    "consultations",
    "expertise",
    "mentoring",
    "equipment_space",
]
HELP_TAGS: Final[tuple[str, ...]] = get_args(HelpTag)
HELP_TYPES: Final[tuple[str, ...]] = get_args(HelpType)
HELPER_KINDS: Final = ("person", "organization")
TEAMMATES: Final = ("yes", "maybe", "no")
ANALOG_WHERE: Final = ("uzbekistan", "abroad")
LOCALES: Final = ("en", "ru", "uz")

HISTORY_KEEP: Final = 5
"""Runs kept per student: the latest and the few before it."""
MAX_PROJECTS: Final = 15
MAX_ANALOGS: Final = 4
MAX_CHALLENGES: Final = 5
MAX_STEPS: Final = 6
MATCHES_PER_PROJECT: Final = 6

LIKES_MAX: Final = 1500
EXPERIENCE_MAX: Final = 1500
NETWORK_MAX: Final = 1000
NOTE_MAX: Final = 300
HOURS_MIN: Final = 0.25
HOURS_MAX: Final = 16.0
BUDGET_MAX: Final = 1_000_000

NAME_MAX: Final = 200
DESCRIPTION_MAX: Final = 1200
AREA_MAX: Final = 80
AREAS_MAX: Final = 12
CITY_MAX: Final = 120
CONTACT_MAX: Final = 200

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[0-9][0-9 ()\-]{5,24}$")
_TELEGRAM = re.compile(
    r"^(@[A-Za-z][A-Za-z0-9_]{4,31}|https://t\.me/[A-Za-z0-9_+/]{2,64})$"
)


@dataclass(frozen=True, slots=True)
class Brief:
    """What the student typed: the only input of the model besides web hits."""

    likes: str
    experience: str
    hours_per_day: float
    teammates: str
    teammates_note: str
    network: str
    budget_min_usd: int
    budget_max_usd: int


@dataclass(frozen=True, slots=True)
class Analog:
    """An existing project like the idea; `url` is only a page the search found."""

    name: str
    where: str
    url: str | None


@dataclass(frozen=True, slots=True)
class ProjectIdea:
    """One suggested project."""

    key: str
    title: str
    summary: str
    analogs: tuple[Analog, ...]
    challenges: tuple[str, ...]
    application_effect: str
    first_steps: tuple[str, ...]
    help_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectRun:
    """One generation for one student."""

    id: UUID
    student_id: UUID
    locale: str
    brief: Brief
    projects: tuple[ProjectIdea, ...]
    model: str
    search_used: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Contacts:
    """How to reach a helper; at least one is set."""

    email: str | None = None
    phone: str | None = None
    telegram: str | None = None
    website: str | None = None

    def any(self) -> bool:
        """Return whether at least one contact is set."""
        return any((self.email, self.phone, self.telegram, self.website))


@dataclass(frozen=True, slots=True)
class Helper:
    """A person or an organization a student can contact about a project."""

    id: UUID
    kind: str
    name: str
    description: Mapping[str, str]
    tags: tuple[str, ...]
    help_types: tuple[str, ...]
    expertise_areas: tuple[str, ...]
    contacts: Contacts
    city: str | None
    active: bool
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = field(default=None)

    def text(self, locale: str) -> str:
        """The description in the locale, else the first one written."""
        for key in (locale, *LOCALES):
            if self.description.get(key):
                return self.description[key]
        return ""


def _invalid(name: str) -> ValidationFailedError:
    return ValidationFailedError(params={"field": name})


def _text(value: Any, name: str, limit: int, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if (required and not text) or len(text) > limit:
        raise _invalid(name)
    return text


def clean_brief(
    *,
    likes: str,
    experience: str,
    hours_per_day: float,
    teammates: str,
    teammates_note: str,
    network: str,
    budget_min_usd: int,
    budget_max_usd: int,
) -> Brief:
    """Return a validated brief; a bad field raises `ValidationFailedError`."""
    if teammates not in TEAMMATES:
        raise _invalid("teammates")
    if not HOURS_MIN <= hours_per_day <= HOURS_MAX:
        raise _invalid("hours_per_day")
    if not 0 <= budget_min_usd <= budget_max_usd <= BUDGET_MAX:
        raise _invalid("budget_max_usd")
    return Brief(
        likes=_text(likes, "likes", LIKES_MAX, required=True),
        experience=_text(experience, "experience", EXPERIENCE_MAX),
        hours_per_day=hours_per_day,
        teammates=teammates,
        teammates_note=_text(teammates_note, "teammates_note", NOTE_MAX),
        network=_text(network, "network", NETWORK_MAX),
        budget_min_usd=budget_min_usd,
        budget_max_usd=budget_max_usd,
    )


def _members(
    values: Iterable[str], allowed: Sequence[str], name: str
) -> tuple[str, ...]:
    out = tuple(dict.fromkeys(str(v).strip() for v in values))
    if any(v not in allowed for v in out):
        raise _invalid(name)
    return out


def _contact(
    value: str | None, name: str, pattern: re.Pattern[str] | None
) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if len(text) > CONTACT_MAX or (pattern and not pattern.match(text)):
        raise _invalid(name)
    return text


def _website(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if len(text) > CONTACT_MAX or not text.startswith("https://") or " " in text:
        raise _invalid("website")
    return text


def clean_contacts(
    *,
    email: str | None,
    phone: str | None,
    telegram: str | None,
    website: str | None,
) -> Contacts:
    """Return validated contacts; at least one must be set."""
    contacts = Contacts(
        email=_contact(email, "email", _EMAIL),
        phone=_contact(phone, "phone", _PHONE),
        telegram=_contact(telegram, "telegram", _TELEGRAM),
        website=_website(website),
    )
    if not contacts.any():
        raise _invalid("contacts")
    return contacts


def clean_helper_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the editable fields of a helper (all present)."""
    kind = str(values["kind"])
    if kind not in HELPER_KINDS:
        raise _invalid("kind")
    description = {
        loc: _text(
            (values["description"] or {}).get(loc, ""), "description", DESCRIPTION_MAX
        )
        for loc in LOCALES
    }
    if not any(description.values()):
        raise _invalid("description")
    areas = tuple(
        dict.fromkeys(
            _text(a, "expertise_areas", AREA_MAX, required=True)
            for a in values["expertise_areas"]
        )
    )
    if len(areas) > AREAS_MAX:
        raise _invalid("expertise_areas")
    tags = _members(values["tags"], HELP_TAGS, "tags")
    if not tags:
        raise _invalid("tags")
    city = _text(values.get("city") or "", "city", CITY_MAX)
    return {
        "kind": kind,
        "name": _text(values["name"], "name", NAME_MAX, required=True),
        "description": description,
        "tags": tags,
        "help_types": _members(values["help_types"], HELP_TYPES, "help_types"),
        "expertise_areas": areas,
        "contacts": clean_contacts(**values["contacts"]),
        "city": city or None,
        "active": bool(values["active"]),
    }


def match_helpers(
    helpers: Iterable[Helper], tags: Iterable[str], *, limit: int = MATCHES_PER_PROJECT
) -> list[Helper]:
    """Active helpers sharing a tag with the project, most shared tags first."""
    wanted = set(tags)
    scored = [
        (len(wanted.intersection(h.tags)), h) for h in helpers if h.active and wanted
    ]
    hits = [(n, h) for n, h in scored if n > 0]
    hits.sort(key=lambda pair: (-pair[0], pair[1].kind != "organization", pair[1].name))
    return [h for _, h in hits[:limit]]
