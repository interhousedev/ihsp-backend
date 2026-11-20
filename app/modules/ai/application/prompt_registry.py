"""Editable prompts: the registry builders and the gateway read, its admin and stats.

`PromptRegistry` keeps the active versions for 30 seconds (like the limits), so a
change made in one process applies in every process within that time; the process
that made it drops its cache at once. Builders that know their locale call
`resolve`; every other call site keeps building its built-in text and the recording
gateway calls `rewrite`, which puts the active versions in place.
"""

import asyncio
import time
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from app.modules.ai.domain.prompt_registry import (
    ALL_LOCALES,
    BUILT_IN_VERSION,
    LOCALES,
    ActiveOverrides,
    PromptRef,
    PromptSlot,
    PromptVersion,
    ResolvedPrompt,
    apply_overrides,
    check_override,
    prompt_hash,
    resolve,
)
from app.modules.ai.domain.requests import (
    PromptDiff,
    estimate_tokens,
    unified_diff,
)
from app.modules.ai.ports.prompts import (
    PromptAnalyticsReader,
    PromptCallStats,
    PromptCallTrace,
    PromptRatingStats,
    PromptVersionLoader,
    PromptVersionRepository,
)
from app.shared.actor import Actor
from app.shared.base_error import NotFoundError, ValidationFailedError
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft

import structlog

log = structlog.get_logger(__name__)

OVERRIDE_TTL_SECONDS = 30.0
AUDIT_PROMPT_SAVED = "admin.prompt_version_saved"
AUDIT_PROMPT_ACTIVATED = "admin.prompt_activated"
AUDIT_PROMPT_REVERTED = "admin.prompt_reverted"

# The versions builders resolved explicitly in this request, by task: the gateway
# counts them in the call's reference (their text is no longer the built-in).
_RESOLVED: ContextVar[dict[str, tuple[PromptVersion, ...]] | None] = ContextVar(
    "ai_resolved_prompts", default=None
)


class PromptNotFoundError(NotFoundError):
    """No such slot, or no such version of it."""

    code = "admin/prompt-not-found"
    message_key = "admin-prompt-not-found"


class PromptInvalidError(ValidationFailedError):
    """The text is empty, too long, or has placeholders the built-in lacks."""

    code = "admin/prompt-invalid"
    message_key = "admin-prompt-invalid"


class PromptRegistry:
    """The built-in slots and their active versions (cached for the TTL)."""

    def __init__(
        self,
        slots: Sequence[PromptSlot],
        loader: PromptVersionLoader,
        *,
        ttl: float = OVERRIDE_TTL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Index the slots; the versions are read on first use."""
        self._slots: dict[tuple[str, str], PromptSlot] = {}
        self._by_task: dict[str, list[PromptSlot]] = {}
        for slot in slots:
            if slot.key in self._slots:
                continue
            self._slots[slot.key] = slot
            self._by_task.setdefault(slot.task, []).append(slot)
        for task_slots in self._by_task.values():
            # longer built-ins first: a slot inside another must not match first
            task_slots.sort(key=lambda s: -len(s.builtin))
        self._loader = loader
        self._ttl = ttl
        self._monotonic = monotonic
        self._active: ActiveOverrides | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def slots(self, task: str | None = None) -> list[PromptSlot]:
        """Every slot (of one task), in catalogue order by task then name."""
        found = [s for s in self._slots.values() if task is None or s.task == task]
        return sorted(found, key=lambda s: s.key)

    def slot(self, task: str, name: str) -> PromptSlot | None:
        """One slot, or None."""
        return self._slots.get((task, name))

    async def resolve(
        self, task: str, name: str, locale: str, default: str | None = None
    ) -> ResolvedPrompt:
        """The active text for the locale, else the built-in (or `default`)."""
        active = await self._overrides()
        resolved = resolve(self.slot(task, name), active, task, name, locale, default)
        found = active.get(task, name, locale)
        if found is not None:
            seen = dict(_RESOLVED.get() or {})
            seen[task] = (*seen.get(task, ()), found)
            _RESOLVED.set(seen)
        return resolved

    async def rewrite(self, task: str | None, system: str) -> tuple[str, PromptRef]:
        """The system prompt with the task's active versions, and what it used."""
        if task is None:
            return system, PromptRef("", BUILT_IN_VERSION, None)
        active = await self._overrides()
        explicit = (_RESOLVED.get() or {}).get(task, ())
        ref: PromptRef | None = None
        if active.has_task(task):
            system, ref = apply_overrides(
                system, task, self._by_task.get(task, ()), active
            )
        if explicit:
            ref = _merge(task, ref, explicit)
        return system, ref or PromptRef(task, BUILT_IN_VERSION, None)

    def invalidate(self) -> None:
        """Drop the cache: the next read goes to storage."""
        self._active = None
        self._expires_at = 0.0

    async def _overrides(self) -> ActiveOverrides:
        if self._active is not None and self._monotonic() < self._expires_at:
            return self._active
        async with self._lock:
            if self._active is not None and self._monotonic() < self._expires_at:
                return self._active
            try:
                self._active = ActiveOverrides.of(await self._loader.active())
            except Exception:
                log.exception("prompt_versions_read_failed")
                if self._active is None:
                    self._active = ActiveOverrides()
            self._expires_at = self._monotonic() + self._ttl
            return self._active


def _merge(
    task: str, ref: PromptRef | None, explicit: Sequence[PromptVersion]
) -> PromptRef:
    parts = [ref.hash or ""] if ref else []
    parts += [f"{v.name}:{v.locale}:{v.version}:{v.hash}" for v in explicit]
    top = max([v.version for v in explicit] + ([ref.version] if ref else []))
    return PromptRef(task, top, prompt_hash("|".join(parts)))


class PromptUnitOfWork(Protocol):
    """One transaction over the prompt versions, with audit events."""

    @property
    def prompts(self) -> PromptVersionRepository:
        """The prompt version repository of the open transaction."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events for commit."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...


@dataclass(frozen=True, slots=True)
class SlotStatus:
    """A slot and its active versions by locale ("" all); none: the built-in."""

    slot: PromptSlot
    active: list[PromptVersion]


@dataclass(frozen=True, slots=True)
class SlotDetail:
    """A slot, the text in force for a locale, and every stored version."""

    slot: PromptSlot
    current: ResolvedPrompt
    versions: list[PromptVersion]


class PromptAdmin:
    """Administrators' changes to the prompts; each one audited, applied at once."""

    def __init__(
        self,
        registry: PromptRegistry,
        uow_factory: Callable[[], PromptUnitOfWork],
        clock: Clock,
    ) -> None:
        """Keep the registry, the transaction factory and the clock."""
        self.registry = registry
        self.uow_factory = uow_factory
        self.clock = clock

    async def catalogue(self, actor: Actor) -> list[SlotStatus]:
        """Every slot with its active versions."""
        async with self.uow_factory() as uow:
            active = await uow.prompts.active()
        by_slot: dict[tuple[str, str], list[PromptVersion]] = {}
        for item in active:
            by_slot.setdefault((item.task, item.name), []).append(item)
        return [
            SlotStatus(slot, sorted(by_slot.get(slot.key, []), key=lambda v: v.locale))
            for slot in self.registry.slots()
        ]

    async def detail(
        self, actor: Actor, task: str, name: str, locale: str = ALL_LOCALES
    ) -> SlotDetail:
        """The slot, the text in force for the locale, and its history."""
        slot = self._slot(task, name)
        _check_locale(locale)
        async with self.uow_factory() as uow:
            versions = await uow.prompts.history(task, name)
        active = ActiveOverrides.of(versions)
        current = resolve(slot, active, task, name, locale)
        return SlotDetail(slot, current, versions)

    async def put_version(
        self,
        actor: Actor,
        task: str,
        name: str,
        *,
        text: str,
        locale: str = ALL_LOCALES,
        note: str = "",
    ) -> PromptVersion:
        """Store a new version and make it the active one of its locale."""
        slot = self._slot(task, name)
        _check_locale(locale)
        reason = check_override(slot, text)
        if reason is not None:
            raise PromptInvalidError(support_details=f"admin/prompt-invalid:{reason}")
        async with self.uow_factory() as uow:
            number = await uow.prompts.next_version(task)
            history = await uow.prompts.history(task, name)
            previous = next(
                (v for v in history if v.active and v.locale == locale), None
            )
            before_text = previous.text if previous else slot.builtin
            before_version = previous.version if previous else BUILT_IN_VERSION
            version = PromptVersion(
                id=new_id(),
                task=task,
                name=name,
                locale=locale,
                version=number,
                text=text,
                hash=prompt_hash(text),
                active=False,
                created_at=self.clock.now(),
                created_by=actor.user_id,
                note=note.strip()[:500],
                source="admin",
                diff=unified_diff(
                    before_text, text, f"v{before_version}", f"v{number}"
                ),
                chars=len(text),
                tokens_est=estimate_tokens(text),
            )
            await uow.prompts.add(version)
            await uow.prompts.activate(task, name, locale, number)
            uow.audit(_audit(AUDIT_PROMPT_SAVED, actor, version))
            await uow.commit()
        self.registry.invalidate()
        return _replace_active(version, True)

    async def activate(
        self, actor: Actor, task: str, name: str, version: int
    ) -> PromptVersion:
        """Make a stored version the active one again (a rollback)."""
        self._slot(task, name)
        async with self.uow_factory() as uow:
            history = await uow.prompts.history(task, name)
            found = next((v for v in history if v.version == version), None)
            if found is None:
                raise PromptNotFoundError()
            await uow.prompts.activate(task, name, found.locale, version)
            uow.audit(_audit(AUDIT_PROMPT_ACTIVATED, actor, found))
            await uow.commit()
        self.registry.invalidate()
        return _replace_active(found, True)

    async def revert(
        self, actor: Actor, task: str, name: str, locale: str = ALL_LOCALES
    ) -> None:
        """Go back to the built-in text for the locale; the history is kept."""
        self._slot(task, name)
        _check_locale(locale)
        async with self.uow_factory() as uow:
            count = await uow.prompts.deactivate(task, name, locale)
            if count:
                uow.audit(
                    AuditDraft(
                        type=AUDIT_PROMPT_REVERTED,
                        actor_id=actor.user_id,
                        metadata={"task": task, "name": name, "locale": locale},
                    )
                )
                await uow.commit()
        self.registry.invalidate()

    async def versions(
        self, actor: Actor, task: str, name: str, locale: str | None = None
    ) -> list[PromptVersion]:
        """The stored versions of the slot (of one locale when given), newest first."""
        self._slot(task, name)
        if locale is not None:
            _check_locale(locale)
        async with self.uow_factory() as uow:
            history = await uow.prompts.history(task, name)
        return [v for v in history if locale is None or v.locale == locale]

    async def diff(
        self,
        actor: Actor,
        task: str,
        name: str,
        *,
        locale: str = ALL_LOCALES,
        from_version: int | None = None,
        to_version: int | None = None,
    ) -> PromptDiff:
        """The unified diff between two versions of the locale (0 is the built-in).

        `to_version` defaults to the latest, `from_version` to the one before it
        (the built-in when there is none).
        """
        slot = self._slot(task, name)
        _check_locale(locale)
        async with self.uow_factory() as uow:
            history = await uow.prompts.history(task, name)
        stored = {v.version: v for v in history if v.locale == locale}
        if to_version is None:
            if not stored:
                raise PromptNotFoundError()
            to_version = max(stored)
        if from_version is None:
            lower = [n for n in stored if n < to_version]
            from_version = max(lower) if lower else BUILT_IN_VERSION
        if from_version >= to_version:
            raise PromptInvalidError(support_details="admin/prompt-invalid:range")
        old = _text_of(slot, stored, from_version)
        new = _text_of(slot, stored, to_version)
        return PromptDiff(
            task=task,
            name=name,
            locale=locale,
            from_version=from_version,
            to_version=to_version,
            diff=unified_diff(old, new, f"v{from_version}", f"v{to_version}"),
            chars_delta=len(new) - len(old),
            tokens_delta=estimate_tokens(new) - estimate_tokens(old),
        )

    def _slot(self, task: str, name: str) -> PromptSlot:
        slot = self.registry.slot(task, name)
        if slot is None:
            raise PromptNotFoundError()
        return slot


def _check_locale(locale: str) -> None:
    if locale != ALL_LOCALES and locale not in LOCALES:
        raise PromptInvalidError(support_details="admin/prompt-invalid:locale")


def _audit(kind: str, actor: Actor, version: PromptVersion) -> AuditDraft:
    # the text itself stays out of the audit log; the hash identifies it
    return AuditDraft(
        type=kind,
        actor_id=actor.user_id,
        metadata={
            "task": version.task,
            "name": version.name,
            "locale": version.locale,
            "version": version.version,
            "hash": version.hash,
        },
    )


def _text_of(slot: PromptSlot, stored: dict[int, PromptVersion], number: int) -> str:
    """The text of a stored version; 0 is the built-in; others must exist."""
    if number == BUILT_IN_VERSION:
        return slot.builtin
    found = stored.get(number)
    if found is None:
        raise PromptNotFoundError()
    return found.text


def _replace_active(version: PromptVersion, active: bool) -> PromptVersion:
    return replace(version, active=active)


@dataclass(frozen=True, slots=True)
class PromptVersionStats:
    """How one task's prompt version (0 built-in) did in a period."""

    task: str
    version: int
    calls: int
    error_rate: float
    p50_ms: float | None
    p95_ms: float | None
    input_tokens: int
    output_tokens: int
    cost_micro: int
    ratings: int
    rating_average: float | None


class PromptAnalytics:
    """Calls, latency, tokens, cost, errors and ratings per task and prompt version."""

    def __init__(self, reader: PromptAnalyticsReader) -> None:
        """Keep the reader."""
        self.reader = reader

    async def report(
        self, actor: Actor, task: str | None, start: datetime, end: datetime
    ) -> list[PromptVersionStats]:
        """The figures of [start, end), by task then version."""
        calls = await self.reader.calls(task, start, end)
        rated = await self.reader.ratings(task, start, end)
        ratings = {(r.task, r.version): r for r in rated}
        rows = [_stats(c, ratings.pop((c.task, c.version), None)) for c in calls]
        # rated messages whose calls fell out of the period still show their ratings
        rows += [
            _stats(PromptCallStats(r.task, r.version, 0, 0, None, None, 0, 0, 0), r)
            for r in ratings.values()
        ]
        return sorted(rows, key=lambda s: (s.task, s.version))

    async def trace(
        self, actor: Actor, task: str, version: int | None, limit: int
    ) -> list[PromptCallTrace]:
        """The latest calls of a task: time, model, tokens, cost, latency, outcome."""
        return await self.reader.trace(task, version, limit)


def _stats(
    call: PromptCallStats, rating: PromptRatingStats | None
) -> PromptVersionStats:
    return PromptVersionStats(
        task=call.task,
        version=call.version,
        calls=call.calls,
        error_rate=call.failed / call.calls if call.calls else 0.0,
        p50_ms=call.p50_ms,
        p95_ms=call.p95_ms,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        cost_micro=call.cost_micro,
        ratings=rating.ratings if rating else 0,
        rating_average=rating.average if rating and rating.ratings else None,
    )
