"""The limits in force for a user: environment, admin overrides, extensions, staff.

`LimitsSettings` holds what the environment says. Administration changes three things
at runtime, without a deploy:

* overrides of the editable limits (``admin.platform_settings``, keys ``limit.<name>``),
* per-user extensions (``admin.limit_extensions``): a multiplier or explicit values,
  with an optional expiry date, applied to that user only (never below the base value),
* staff are not limited by the quota fields at all (`ActorLimits` reports ``None``).

`EffectiveLimits` reads all of it in one snapshot and caches the snapshot for a short
time. Checks ask for ``await limits.for_actor(actor)`` (or ``for_user``) and read
attributes with the names of `LimitsSettings`; a quota is ``None`` when unlimited.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol
from uuid import UUID

from app.settings import LimitsSettings
from app.shared.actor import Actor, Role

import structlog

log = structlog.get_logger(__name__)

OVERRIDE_TTL_SECONDS = 30.0
"""How long a process keeps the snapshot it read (other processes see a change then)."""

LIMIT_PREFIXES: tuple[str, ...] = ("ai_", "nb_", "lms_ai_", "web_search_")
"""Name prefixes of the limits Administration may change."""

NOT_EDITABLE: frozenset[str] = frozenset({"ai_smart_weight"})
"""Deprecated alias the settings resolve once into a task's budget weight."""

QUOTA_MARKERS: tuple[str, ...] = ("tokens", "per_day", "per_week")
"""Name parts of the quota limits: staff are not limited by these (rates are kept)."""

UNLIMITED = -1
"""The value of a limit with no cap (set and stored as -1; readers see ``None``)."""

UNLIMITABLE: frozenset[str] = frozenset(
    {
        "ai_session_tokens_student",
        "ai_daily_tokens_student",
        "ai_smart_requests_per_week_student",
        "nb_session_tokens_student",
        "nb_daily_tokens_student",
        "nb_artifacts_per_day",
        "nb_slides_per_day",
        "nb_infographics_per_day",
        "nb_web_materials_per_day",
        "nb_media_described_per_day",
        "web_search_per_day_student",
    }
)
"""Editable quotas (token budgets and per-day or per-week counts) that may be -1.

Sizes, rates, timeouts and step counts have no meaning as unlimited and are not here.
"""

STAFF_ROLES: frozenset[Role] = frozenset(
    {Role.TEACHER, Role.ADMIN, Role.LMS_ADMIN, Role.LMS_CREATOR, Role.LIBRARIAN}
)


def is_limit(name: str) -> bool:
    """True for a field Administration may change."""
    return (
        name.startswith(LIMIT_PREFIXES)
        and name not in NOT_EDITABLE
        and name in LimitsSettings.model_fields
    )


def is_quota(name: str) -> bool:
    """True for an editable quota (tokens or counts per day or week)."""
    return is_limit(name) and any(marker in name for marker in QUOTA_MARKERS)


def is_unlimitable(name: str) -> bool:
    """True for a limit that may be set to -1 (no cap)."""
    return name in UNLIMITABLE


def is_scalable(name: str) -> bool:
    """True when a per-user multiplier applies (counts and token budgets, not sizes)."""
    return not any(part in name for part in ("hours", "bytes"))


def is_unlimited(actor: Actor) -> bool:
    """Staff (any role but student) are not limited by quotas."""
    return is_unlimited_roles(actor.roles)


def is_unlimited_roles(roles: Iterable[Role]) -> bool:
    """The rule of `is_unlimited` for a set of roles; no student role means staff."""
    held = set(roles)
    return Role.STUDENT not in held or bool(held & STAFF_ROLES)


@dataclass(frozen=True, slots=True)
class LimitExtension:
    """What Administration grants one student on top of the limits (see module doc)."""

    multiplier: int | None = None
    values: Mapping[str, int] = field(default_factory=dict)
    expires_on: date | None = None

    def active_on(self, day: date) -> bool:
        """True until the expiry date (inclusive) and forever without one."""
        return self.expires_on is None or day <= self.expires_on


@dataclass(frozen=True, slots=True)
class LimitSnapshot:
    """Everything the provider reads from storage in one go."""

    overrides: Mapping[str, Any] = field(default_factory=dict)
    extensions: Mapping[UUID, LimitExtension] = field(default_factory=dict)


class ActorLimits:
    """The limits one user is checked against.

    Attribute access returns the limit with the name of `LimitsSettings`. For an
    unlimited user (staff) every quota reads ``None``: callers treat ``None`` as "no
    cap". Rates (per minute), sizes and tool steps keep their values for everyone.
    """

    __slots__ = ("values", "unlimited")

    def __init__(self, values: LimitsSettings, *, unlimited: bool) -> None:
        """Keep the effective values and whether the user is unlimited."""
        self.values = values
        self.unlimited = unlimited

    def __getattr__(self, name: str) -> Any:
        """Return the limit: None for -1 (no cap) and for an unlimited user's quota."""
        if self.unlimited and is_quota(name):
            return None
        value = getattr(self.values, name)
        if value == UNLIMITED and is_unlimitable(name):
            return None
        return value


def apply_overrides(
    base: LimitsSettings, overrides: Mapping[str, Any]
) -> LimitsSettings:
    """Return ``base`` with the given field values replaced (unknown names are ignored).

    The values must already be valid: the loader validates them when it reads them.
    """
    known = {
        name: value
        for name, value in overrides.items()
        if name in LimitsSettings.model_fields
    }
    return base.model_copy(update=known) if known else base


def apply_extension(base: LimitsSettings, extension: LimitExtension) -> LimitsSettings:
    """Raise the limits of one user: the larger of the base value and the extension.

    The multiplier scales every count and token budget; explicit values set a floor for
    their key. An extension never lowers a limit, and a -1 (no cap) stays -1.
    """
    updates: dict[str, int] = {}
    for name in LimitsSettings.model_fields:
        if not is_limit(name):
            continue
        value = getattr(base, name)
        if not isinstance(value, int) or isinstance(value, bool):
            continue
        new = _extended(name, value, extension)
        if new != value:
            updates[name] = new
    return base.model_copy(update=updates) if updates else base


def _extended(name: str, value: int, extension: LimitExtension) -> int:
    """One limit under an extension: a -1 stays, an explicit -1 grant lifts it."""
    if value == UNLIMITED and is_unlimitable(name):
        return value
    new = value
    if extension.multiplier and is_scalable(name):
        new = max(new, value * extension.multiplier)
    if name in extension.values:
        granted = int(extension.values[name])
        if granted == UNLIMITED and is_unlimitable(name):
            return UNLIMITED
        new = max(new, granted)
    return new


class LimitsProvider(Protocol):
    """Source of the limits a check should use right now."""

    async def current(self) -> LimitsSettings:
        """Return the environment's limits with the overrides applied (no user)."""
        ...

    async def for_user(
        self, user_id: UUID, *, unlimited: bool | None = None
    ) -> ActorLimits:
        """Return the limits of one user: overrides, the user's extension, staff.

        `unlimited` is the caller's knowledge of the user (an assistant of staff, a
        course pool); None lets the provider decide from the user's roles.
        """
        ...

    async def for_actor(self, actor: Actor) -> ActorLimits:
        """Return the limits of the actor (staff are unlimited)."""
        ...

    def invalidate(self) -> None:
        """Forget the cached snapshot; the next read goes to storage."""
        ...


class _ProviderBase:
    async def for_actor(self, actor: Actor) -> ActorLimits:
        """The limits of the actor: staff unlimited, students with their extension."""
        return await self.for_user(actor.user_id, unlimited=is_unlimited(actor))

    async def for_user(
        self, user_id: UUID, *, unlimited: bool | None = None
    ) -> ActorLimits:
        raise NotImplementedError


class StaticLimits(_ProviderBase):
    """The environment's limits only (tests and modules built without storage)."""

    def __init__(self, limits: LimitsSettings) -> None:
        """Keep the limits."""
        self._limits = limits

    async def current(self) -> LimitsSettings:
        """Return the environment's limits."""
        return self._limits

    async def for_user(
        self, user_id: UUID, *, unlimited: bool | None = None
    ) -> ActorLimits:
        """The environment's limits; nobody is staff unless the caller says so."""
        return ActorLimits(self._limits, unlimited=bool(unlimited))

    def invalidate(self) -> None:
        """Nothing is cached."""


class EffectiveLimits(_ProviderBase):
    """The environment's limits plus the stored snapshot, cached for `ttl` seconds."""

    def __init__(
        self,
        base: LimitsSettings,
        load: Callable[[], Awaitable[LimitSnapshot]],
        *,
        today: Callable[[], date],
        roles: Callable[[UUID], Awaitable[Iterable[Role]]] | None = None,
        ttl: float = OVERRIDE_TTL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Keep the limits, the snapshot loader, the day and the role lookup.

        The role lookup tells who is staff when a caller does not say; `ttl` is in
        seconds.
        """
        self._base = base
        self._load = load
        self._today = today
        self._roles = roles
        self._ttl = ttl
        self._monotonic = monotonic
        self._effective: LimitsSettings | None = None
        self._snapshot = LimitSnapshot()
        self._expires_at = 0.0
        self._roles_seen: dict[UUID, tuple[float, bool]] = {}
        self._lock = asyncio.Lock()

    async def current(self) -> LimitsSettings:
        """Return the environment's limits with the overrides applied."""
        effective, _ = await self._state()
        return effective

    async def for_user(
        self, user_id: UUID, *, unlimited: bool | None = None
    ) -> ActorLimits:
        """The user's limits: the effective values raised by an active extension."""
        effective, snapshot = await self._state()
        if unlimited is None:
            unlimited = await self._is_staff(user_id)
        extension = snapshot.extensions.get(user_id)
        if (
            extension is not None
            and not unlimited
            and extension.active_on(self._today())
        ):
            effective = apply_extension(effective, extension)
        return ActorLimits(effective, unlimited=unlimited)

    def invalidate(self) -> None:
        """Drop the caches: the next read goes to storage."""
        self._effective = None
        self._expires_at = 0.0
        self._roles_seen.clear()

    async def _is_staff(self, user_id: UUID) -> bool:
        """Whether the user is unlimited by role; the answer is cached for the TTL."""
        if self._roles is None:
            return False
        now = self._monotonic()
        seen = self._roles_seen.get(user_id)
        if seen is not None and now < seen[0]:
            return seen[1]
        try:
            unlimited = is_unlimited_roles(await self._roles(user_id))
        except Exception:
            log.exception("limit_roles_read_failed")
            return False
        self._roles_seen[user_id] = (now + self._ttl, unlimited)
        return unlimited

    async def _state(self) -> tuple[LimitsSettings, LimitSnapshot]:
        if self._fresh():
            return self._current_state()
        async with self._lock:
            if self._fresh():
                return self._current_state()
            try:
                snapshot = await self._load()
            except Exception:
                log.exception("limit_snapshot_read_failed")
                if self._effective is not None:
                    return self._current_state()
                snapshot = LimitSnapshot()
            self._snapshot = snapshot
            self._effective = apply_overrides(self._base, snapshot.overrides)
            self._expires_at = self._monotonic() + self._ttl
            return self._current_state()

    def _fresh(self) -> bool:
        return self._effective is not None and self._monotonic() < self._expires_at

    def _current_state(self) -> tuple[LimitsSettings, LimitSnapshot]:
        assert self._effective is not None
        return self._effective, self._snapshot
