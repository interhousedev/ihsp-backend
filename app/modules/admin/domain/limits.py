"""Runtime limits Administration may change: the catalogue, validation and extensions.

The catalogue is read from the settings class (`LimitsSettings`): a new limit field with
an ``ai_``, ``nb_``, ``lms_ai_`` or ``web_search_`` name appears here without code
changes. Staff are not limited by quotas, so the staff-only quotas (``lms_ai_*`` pools,
``*_staff``) are not listed: they have no effect and are hidden from the editor.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cache
from typing import Any
from uuid import UUID

from app.settings import LimitsSettings
from app.shared.base_error import ValidationFailedError
from app.shared.limits import UNLIMITED, is_limit, is_quota, is_unlimitable
from app.shared.settings_docs import field_docs

OVERRIDE_PREFIX = "limit."
"""Keys of the overrides in ``admin.platform_settings``: ``limit.<field name>``."""

MULTIPLIER_MIN = 2
MULTIPLIER_MAX = 10
NOTE_MAX_LENGTH = 500

_AT_LEAST_ONE: frozenset[str] = frozenset(
    {
        "ai_session_hours",
        "ai_max_tool_steps",
        "lms_ai_max_tool_steps",
        "nb_concurrent_artifacts",
    }
)
_MAX_BY_UNIT: dict[str, int] = {
    "tokens": 1_000_000_000,
    "bytes": 1_073_741_824,
    "hours": 720,
    "steps": 100,
    "count": 100_000,
    "switch": 1,
}
_SWITCHES: frozenset[str] = frozenset({"ai_ask_before_web_search"})
"""0/1 limits: the editor shows a switch instead of a number."""


class LimitInvalidError(ValidationFailedError):
    """A limit value is not a whole number in its bounds, or its name is unknown."""

    code = "admin/limit-invalid"
    message_key = "admin-limit-invalid"


class LimitExtensionInvalidError(ValidationFailedError):
    """An extension has no grant, a bad multiplier or value, or a past expiry date."""

    code = "admin/limit-extension-invalid"
    message_key = "admin-limit-extension-invalid"


def is_hidden(name: str) -> bool:
    """Staff-only quotas: staff are unlimited, so the editor does not show them."""
    return is_quota(name) and (name.startswith("lms_ai_") or name.endswith("_staff"))


def group_of(name: str) -> str:
    """The editor group of a limit."""
    if name.startswith("lms_ai_"):
        return "lms"
    if name.startswith("nb_"):
        return "notebooks"
    if name.startswith("web_search_"):
        return "web_search"
    if "smart" in name:
        return "smart"
    return "assistant"


def unit_of(name: str) -> str:
    """What the number counts: tokens, steps, hours, bytes, counts or a 0/1 switch."""
    if name in _SWITCHES:
        return "switch"
    if "tokens" in name:
        return "tokens"
    if name.endswith("_bytes"):
        return "bytes"
    if name.endswith("_hours"):
        return "hours"
    if "tool_steps" in name:
        return "steps"
    return "count"


def period_of(name: str) -> str | None:
    """The window a limit counts over, or None for a standing limit."""
    if "session" in name:
        return "session"
    if "daily" in name or "per_day" in name:
        return "day"
    if "per_week" in name:
        return "week"
    if "per_minute" in name:
        return "minute"
    if "per_hour" in name:
        return "hour"
    return None


@dataclass(frozen=True, slots=True)
class LimitSpec:
    """One editable limit: how it is grouped, measured and bounded."""

    key: str
    group: str
    unit: str
    period: str | None
    minimum: int
    maximum: int
    description: str
    unlimitable: bool = False
    """True when -1 (no cap) is valid; the editor shows an "Unlimited" toggle."""


@cache
def editable_specs() -> tuple[LimitSpec, ...]:
    """Every editable limit of `LimitsSettings`, in declaration order."""
    docs = _docs()
    specs: list[LimitSpec] = []
    for name, info in LimitsSettings.model_fields.items():
        if not is_limit(name) or is_hidden(name):
            continue
        unit = unit_of(name)
        minimum = 1 if name in _AT_LEAST_ONE else 0
        maximum = _MAX_BY_UNIT[unit]
        for meta in info.metadata:
            ge = getattr(meta, "ge", None)
            le = getattr(meta, "le", None)
            if ge is not None:
                minimum = max(minimum, int(ge))
            if le is not None:
                maximum = min(maximum, int(le))
        specs.append(
            LimitSpec(
                key=name,
                group=group_of(name),
                unit=unit,
                period=period_of(name),
                minimum=minimum,
                maximum=maximum,
                description=docs.get(name, ""),
                unlimitable=is_unlimitable(name),
            )
        )
    return tuple(specs)


def spec_of(key: str) -> LimitSpec:
    """The spec of an editable limit; an unknown or hidden name is refused."""
    for spec in editable_specs():
        if spec.key == key:
            return spec
    raise LimitInvalidError(params={"field": key})


def check_value(spec: LimitSpec, value: Any) -> int | None:
    """Return the value (None = reset to the environment's value) or raise.

    -1 (no cap) is accepted only for the limits that allow it; every other limit takes
    its normal range.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise LimitInvalidError(params=_bounds(spec))
    if spec.unlimitable and value == UNLIMITED:
        return value
    if not spec.minimum <= value <= spec.maximum:
        raise LimitInvalidError(params=_bounds(spec))
    return value


def stored_key(key: str) -> str:
    """The key of an override in ``admin.platform_settings``."""
    return f"{OVERRIDE_PREFIX}{key}"


def overrides_from_rows(rows: dict[str, Any]) -> dict[str, int]:
    """The valid overrides among the stored rows (others are ignored)."""
    valid: dict[str, int] = {}
    for key, value in rows.items():
        if not key.startswith(OVERRIDE_PREFIX):
            continue
        name = key[len(OVERRIDE_PREFIX) :]
        try:
            spec = spec_of(name)
            checked = check_value(spec, value)
        except LimitInvalidError:
            continue
        if checked is not None:
            valid[name] = checked
    return valid


@dataclass(frozen=True, slots=True)
class ExtensionTerms:
    """What an extension grants: a multiplier, explicit values, an expiry and a note."""

    multiplier: int | None = None
    values: dict[str, int] = field(default_factory=dict)
    expires_on: date | None = None
    note: str = ""


def check_extension(terms: ExtensionTerms, today: date) -> ExtensionTerms:
    """Validate the terms; the expiry date must not be in the past."""
    if terms.multiplier is None and not terms.values:
        raise LimitExtensionInvalidError(params={"reason": "empty"})
    if (
        terms.multiplier is not None
        and not MULTIPLIER_MIN <= terms.multiplier <= MULTIPLIER_MAX
    ):
        raise LimitExtensionInvalidError(
            params={
                "reason": "multiplier",
                "min": MULTIPLIER_MIN,
                "max": MULTIPLIER_MAX,
            }
        )
    values: dict[str, int] = {}
    for key, value in terms.values.items():
        spec = _spec_or_extension_error(key)
        checked = check_value(spec, value)
        if checked is None:
            raise LimitExtensionInvalidError(params={"reason": "value", "field": key})
        values[key] = checked
    if terms.expires_on is not None and terms.expires_on < today:
        raise LimitExtensionInvalidError(params={"reason": "expires"})
    if len(terms.note) > NOTE_MAX_LENGTH:
        raise LimitExtensionInvalidError(
            params={"reason": "note", "max": NOTE_MAX_LENGTH}
        )
    return ExtensionTerms(
        multiplier=terms.multiplier,
        values=values,
        expires_on=terms.expires_on,
        note=terms.note.strip(),
    )


def _spec_or_extension_error(key: str) -> LimitSpec:
    try:
        return spec_of(key)
    except LimitInvalidError as exc:
        raise LimitExtensionInvalidError(
            params={"reason": "field", "field": key}
        ) from exc


def _bounds(spec: LimitSpec) -> dict[str, Any]:
    return {"field": spec.key, "min": spec.minimum, "max": spec.maximum}


def _docs() -> dict[str, str]:
    try:
        return field_docs(LimitsSettings)
    except Exception:  # the source is not available: the editor shows the key only
        return {}


@dataclass(frozen=True, slots=True)
class ExtensionRecord:
    """A stored extension: who it is for, its terms and when it changed."""

    user_id: UUID
    terms: ExtensionTerms
    created_at: datetime
    updated_at: datetime
    updated_by: UUID | None = None
