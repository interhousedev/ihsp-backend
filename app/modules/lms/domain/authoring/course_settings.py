"""Course settings (profile, landing page, audience, enrolment, navigation).

Pure validation: `validate_settings` takes a partial change and returns the
normalised values; nothing here touches storage.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from app.modules.lms.domain.authoring.entities import Course
from app.modules.lms.domain.authoring.enums import CourseStatus
from app.modules.lms.domain.authoring.errors import SettingsInvalidError

LANGUAGES: Final = ("uz", "ru", "en")
LEVELS: Final = ("beginner", "intermediate", "advanced")
AUDIENCE_SCOPES: Final = ("link", "group", "lyceum", "public")
NAV_KEYS: Final = (
    "overview",
    "syllabus",
    "announcements",
    "people",
    "grades",
    "files",
    "notebooks",
    "discussions",
)
MAX_TAGS: Final = 10
MAX_TAG_LENGTH: Final = 32
MAX_OUTCOMES: Final = 12
MAX_LIST_ITEMS: Final = 12
MAX_ITEM_LENGTH: Final = 200
MAX_GROUPS: Final = 50
_COLOR: Final = re.compile(r"^#[0-9a-fA-F]{6}$")

TEXT_LISTS: Final = {
    "tags": (MAX_TAGS, MAX_TAG_LENGTH),
    "outcomes": (MAX_OUTCOMES, MAX_ITEM_LENGTH),
    "requirements": (MAX_LIST_ITEMS, MAX_ITEM_LENGTH),
    "audience": (MAX_LIST_ITEMS, MAX_ITEM_LENGTH),
}


@dataclass(frozen=True, slots=True)
class CourseSettings:
    """The settings of a course as the editor shows them."""

    code: str | None
    friendly_name: str | None
    summary: str
    accent_color: str | None
    language: str
    level: str | None
    workload_hours_per_week: int | None
    duration_weeks: int | None
    tags: list[str]
    outcomes: list[str]
    requirements: list[str]
    audience: list[str]
    audience_scope: str
    audience_group_ids: list[str]
    enrolment_open: bool
    enrolment_starts_at: datetime | None
    enrolment_ends_at: datetime | None
    navigation: list[dict[str, Any]]


def derive_publish_state(course: Course) -> str:
    """Return draft, published or archived from the status and the live version."""
    if course.status is CourseStatus.ARCHIVED:
        return "archived"
    return "published" if course.live_version_id is not None else "draft"


def bad(field: str, reason: str) -> SettingsInvalidError:
    """Return the validation error for one field."""
    return SettingsInvalidError(params={"field": field, "reason": reason})


def clean_color(value: str | None) -> str | None:
    """Return a `#rrggbb` colour (lower case) or None."""
    if value is None or value == "":
        return None
    if not _COLOR.match(value):
        raise bad("accent_color", "hex")
    return value.lower()


def clean_choice(field: str, value: str, allowed: tuple[str, ...]) -> str:
    """Return the value if it is one of the allowed ones."""
    if value not in allowed:
        raise bad(field, "choice")
    return value


def clean_range(field: str, value: int | None, low: int, high: int) -> int | None:
    """Return the integer if it lies in `low..high`; None stays None."""
    if value is None:
        return None
    if isinstance(value, bool) or not low <= value <= high:
        raise bad(field, "range")
    return value


def clean_text_list(field: str, value: list[str]) -> list[str]:
    """Strip items, drop empty ones and duplicates, enforce the limits."""
    max_items, max_length = TEXT_LISTS[field]
    result: list[str] = []
    for item in value:
        text = item.strip()
        if not text or text in result:
            continue
        if len(text) > max_length:
            raise bad(field, "item-too-long")
        result.append(text)
    if len(result) > max_items:
        raise bad(field, "too-many")
    return result


def clean_navigation(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate `[{key, hidden}]`: known keys, each at most once, order kept."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        key = item.get("key")
        if key not in NAV_KEYS or key in seen:
            raise bad("navigation", "key")
        seen.add(key)
        result.append({"key": key, "hidden": bool(item.get("hidden", False))})
    return result


def clean_window(
    starts: datetime | None, ends: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """Require the enrolment end to be after the start."""
    if starts is not None and ends is not None and ends <= starts:
        raise bad("enrolment_ends_at", "before-start")
    return starts, ends


def default_navigation() -> list[dict[str, Any]]:
    """Return every section, none hidden."""
    return [{"key": key, "hidden": False} for key in NAV_KEYS]


def to_settings(course: Course) -> CourseSettings:
    """Return the settings stored on the course."""
    return CourseSettings(
        code=course.code,
        friendly_name=course.friendly_name,
        summary=course.summary,
        accent_color=course.accent_color,
        language=course.language,
        level=course.level,
        workload_hours_per_week=course.workload_hours_per_week,
        duration_weeks=course.duration_weeks,
        tags=list(course.tags),
        outcomes=list(course.outcomes),
        requirements=list(course.requirements),
        audience=list(course.audience),
        audience_scope=course.audience_scope,
        audience_group_ids=list(course.audience_group_ids),
        enrolment_open=course.enrolment_open,
        enrolment_starts_at=course.enrolment_starts_at,
        enrolment_ends_at=course.enrolment_ends_at,
        navigation=list(course.navigation) or default_navigation(),
    )


def apply_settings(course: Course, changes: dict[str, Any]) -> None:
    """Validate the partial `changes` and write them onto the course.

    Raises:
        SettingsInvalidError: A value is out of range; the course is unchanged.
    """
    clean = {field: _clean_field(field, value) for field, value in changes.items()}
    starts = clean.get("enrolment_starts_at", course.enrolment_starts_at)
    ends = clean.get("enrolment_ends_at", course.enrolment_ends_at)
    clean_window(starts, ends)
    for field, value in clean.items():
        setattr(course, field, value)


def _clean_groups(field: str, value: Any) -> list[str]:
    """Cap the audience group count and drop duplicates."""
    if len(value) > MAX_GROUPS:
        raise bad(field, "too-many")
    return [str(v) for v in dict.fromkeys(value)]


_CLEANERS: dict[str, Callable[[str, Any], Any]] = {
    "accent_color": lambda f, v: clean_color(v),
    "language": lambda f, v: clean_choice(f, v, LANGUAGES),
    "level": lambda f, v: None if v is None else clean_choice(f, v, LEVELS),
    "audience_scope": lambda f, v: clean_choice(f, v, AUDIENCE_SCOPES),
    "workload_hours_per_week": lambda f, v: clean_range(f, v, 1, 40),
    "duration_weeks": lambda f, v: clean_range(f, v, 1, 52),
    "navigation": lambda f, v: clean_navigation(v),
    "summary": lambda f, v: _bounded(f, v, 500, required=True),
    "code": lambda f, v: _bounded(f, v, 32),
    "friendly_name": lambda f, v: _bounded(f, v, 255),
    "audience_group_ids": _clean_groups,
}


def _clean_field(field: str, value: Any) -> Any:
    """Validate one settings field and return the value to store."""
    if field in TEXT_LISTS:
        return clean_text_list(field, value)
    cleaner = _CLEANERS.get(field)
    return cleaner(field, value) if cleaner else value


def _bounded(
    field: str, value: str | None, limit: int, *, required: bool = False
) -> str | None:
    """Strip the text and enforce its length; empty becomes None unless required."""
    text = (value or "").strip()
    if len(text) > limit:
        raise bad(field, "too-long")
    if not text:
        return "" if required else None
    return text
