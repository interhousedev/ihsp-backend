"""Editable prompts: resolution, the cache, versions, the ledger and the analytics."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self
from uuid import uuid4

from app.modules.ai.application.prompt_registry import (
    AUDIT_PROMPT_ACTIVATED,
    AUDIT_PROMPT_REVERTED,
    AUDIT_PROMPT_SAVED,
    PromptAdmin,
    PromptAnalytics,
    PromptInvalidError,
    PromptNotFoundError,
    PromptRegistry,
)
from app.modules.ai.domain.prompt_registry import (
    BUILT_IN_VERSION,
    PromptSlot,
    PromptVersion,
    check_override,
    prompt_hash,
)
from app.modules.ai.domain.usage import UsageEvent
from app.modules.ai.infrastructure.recording_gateways import (
    RecordingLlmGateway,
    UsageRecorder,
)
from app.modules.ai.ports.prompts import PromptCallStats, PromptRatingStats
from app.shared.actor import Actor, Role
from app.shared.contracts.ai import LlmTuning
from app.shared.notifications import AuditDraft
from tests.fakes.clock import FixedClock

import pytest

NOW = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
TASK = "chat"
INTRO = PromptSlot(TASK, "intro", "Who the assistant is", "You are a helper.")
GREET = PromptSlot(TASK, "greet", "The greeting", "Greet {name} kindly.", template=True)
ADMIN = Actor(user_id=uuid4(), roles=frozenset({Role.ADMIN}))


def version(
    number: int,
    text: str,
    *,
    name: str = "intro",
    locale: str = "",
    active: bool = True,
) -> PromptVersion:
    return PromptVersion(
        id=uuid4(),
        task=TASK,
        name=name,
        locale=locale,
        version=number,
        text=text,
        hash=prompt_hash(text),
        active=active,
        created_at=NOW,
    )


class Loader:
    """Active versions from memory; counts the reads."""

    def __init__(self, versions: Sequence[PromptVersion] = ()) -> None:
        self.versions = list(versions)
        self.reads = 0
        self.broken = False

    async def active(self) -> Sequence[PromptVersion]:
        self.reads += 1
        if self.broken:
            raise RuntimeError("db down")
        return [v for v in self.versions if v.active]


class Ticker:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Repo:
    """The version store in memory (shared with the loader)."""

    def __init__(self, loader: Loader) -> None:
        self.loader = loader

    async def history(self, task: str, name: str) -> list[PromptVersion]:
        found = [v for v in self.loader.versions if (v.task, v.name) == (task, name)]
        return sorted(found, key=lambda v: -v.version)

    async def active(self, task: str | None = None) -> list[PromptVersion]:
        return [v for v in self.loader.versions if v.active]

    async def next_version(self, task: str) -> int:
        numbers = [v.version for v in self.loader.versions if v.task == task]
        return max(numbers, default=0) + 1

    async def add(self, item: PromptVersion) -> None:
        self.loader.versions.append(item)

    async def activate(self, task: str, name: str, locale: str, number: int) -> bool:
        hit = False
        rows = []
        for v in self.loader.versions:
            if (v.task, v.name, v.locale) == (task, name, locale):
                hit = hit or v.version == number
                v = replace(v, active=v.version == number)
            rows.append(v)
        self.loader.versions = rows
        return hit

    async def deactivate(self, task: str, name: str, locale: str) -> int:
        count = 0
        rows = []
        for v in self.loader.versions:
            if (v.task, v.name, v.locale) == (task, name, locale) and v.active:
                count += 1
                v = replace(v, active=False)
            rows.append(v)
        self.loader.versions = rows
        return count


class Uow:
    def __init__(self, repo: Repo, audits: list[AuditDraft]) -> None:
        self.prompts = repo
        self.audits = audits
        self.pending: list[AuditDraft] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.pending.clear()

    def audit(self, *drafts: AuditDraft) -> None:
        self.pending.extend(drafts)

    async def commit(self) -> None:
        self.audits.extend(self.pending)
        self.pending.clear()


def setup(
    versions: Sequence[PromptVersion] = (),
) -> tuple[PromptRegistry, Loader, Ticker, PromptAdmin, list[AuditDraft]]:
    loader = Loader(versions)
    ticker = Ticker()
    registry = PromptRegistry([INTRO, GREET], loader, ttl=30, monotonic=ticker)
    audits: list[AuditDraft] = []
    repo = Repo(loader)
    admin = PromptAdmin(registry, lambda: Uow(repo, audits), FixedClock(NOW))
    return registry, loader, ticker, admin, audits


async def test_resolve_falls_back_to_the_built_in() -> None:
    registry, *_ = setup()
    found = await registry.resolve(TASK, "intro", "ru")
    assert (found.text, found.version) == ("You are a helper.", BUILT_IN_VERSION)
    assert found.hash == prompt_hash("You are a helper.")
    missing = await registry.resolve(TASK, "nothing", "ru", default="Fallback")
    assert missing.text == "Fallback"


async def test_resolve_prefers_the_locale_then_all_locales() -> None:
    registry, *_ = setup(
        [version(1, "Every locale."), version(2, "Только русский.", locale="ru")]
    )
    assert (await registry.resolve(TASK, "intro", "ru")).version == 2
    english = await registry.resolve(TASK, "intro", "en")
    assert (english.text, english.version) == ("Every locale.", 1)


async def test_cache_lasts_the_ttl_then_reloads() -> None:
    registry, loader, ticker, *_ = setup([version(1, "First.")])
    assert (await registry.resolve(TASK, "intro", "")).text == "First."
    loader.versions = [version(1, "First.", active=False), version(2, "Second.")]
    ticker.now = 29.0
    assert (await registry.resolve(TASK, "intro", "")).text == "First."
    ticker.now = 31.0
    assert (await registry.resolve(TASK, "intro", "")).text == "Second."
    assert loader.reads == 2


async def test_failed_reload_keeps_the_last_versions() -> None:
    registry, loader, ticker, *_ = setup([version(1, "First.")])
    await registry.resolve(TASK, "intro", "")
    loader.broken = True
    ticker.now = 60.0
    assert (await registry.resolve(TASK, "intro", "")).text == "First."


async def test_rewrite_replaces_literal_and_template_slots() -> None:
    registry, *_ = setup(
        [version(3, "You are a tutor."), version(4, "Hi {name}!", name="greet")]
    )
    system, ref = await registry.rewrite(
        TASK, "You are a helper. Greet Aziza kindly. Rules."
    )
    assert system == "You are a tutor. Hi Aziza! Rules."
    assert (ref.task, ref.version) == (TASK, 4)
    assert ref.hash is not None


async def test_rewrite_without_overrides_is_built_in() -> None:
    registry, *_ = setup()
    system, ref = await registry.rewrite(TASK, "You are a helper.")
    assert system == "You are a helper."
    assert (ref.version, ref.hash) == (BUILT_IN_VERSION, None)


def test_check_override_rejects_bad_texts() -> None:
    assert check_override(INTRO, "  ") == "empty"
    assert check_override(GREET, "Hi {name} from {city}") == "unknown_placeholder"
    assert check_override(GREET, "Hi {name}") is None
    assert check_override(INTRO, "x" * 100_000) == "too_long"


async def test_put_activate_and_revert_are_audited_and_applied_at_once() -> None:
    registry, loader, _, admin, audits = setup()
    assert (await registry.resolve(TASK, "intro", "")).version == 0
    first = await admin.put_version(ADMIN, TASK, "intro", text="One.")
    second = await admin.put_version(ADMIN, TASK, "intro", text="Two.", note="try")
    assert (first.version, second.version, second.active) == (1, 2, True)
    # no waiting for the TTL: the writer drops the cache
    assert (await registry.resolve(TASK, "intro", "")).text == "Two."

    back = await admin.activate(ADMIN, TASK, "intro", 1)
    assert back.text == "One."
    assert (await registry.resolve(TASK, "intro", "")).text == "One."
    detail = await admin.detail(ADMIN, TASK, "intro")
    assert [v.version for v in detail.versions] == [2, 1]
    assert [v.active for v in detail.versions] == [False, True]

    await admin.revert(ADMIN, TASK, "intro")
    assert (await registry.resolve(TASK, "intro", "")).version == 0
    assert len(loader.versions) == 2  # the history stays
    assert [a.type for a in audits] == [
        AUDIT_PROMPT_SAVED,
        AUDIT_PROMPT_SAVED,
        AUDIT_PROMPT_ACTIVATED,
        AUDIT_PROMPT_REVERTED,
    ]
    assert all("text" not in a.metadata for a in audits)


async def test_admin_rejects_unknown_slots_versions_and_bad_text() -> None:
    _, _, _, admin, audits = setup()
    with pytest.raises(PromptNotFoundError):
        await admin.put_version(ADMIN, TASK, "nothing", text="x")
    with pytest.raises(PromptNotFoundError):
        await admin.activate(ADMIN, TASK, "intro", 9)
    with pytest.raises(PromptInvalidError):
        await admin.put_version(ADMIN, TASK, "greet", text="Hi {city}")
    with pytest.raises(PromptInvalidError):
        await admin.put_version(ADMIN, TASK, "intro", text="x", locale="de")
    assert audits == []


class Sink:
    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    async def write(self, event: UsageEvent) -> None:
        self.events.append(event)


class Inner:
    def __init__(self) -> None:
        self.systems: list[str] = []

    async def complete(self, **call: Any) -> dict[str, Any]:
        self.systems.append(call["system"])
        return {"text": "ok", "tool_calls": [], "usage": {"input": 5, "output": 2}}


async def test_usage_row_carries_the_prompt_version() -> None:
    registry, *_ = setup([version(7, "You are a tutor.")])
    sink = Sink()
    inner = Inner()
    gateway = RecordingLlmGateway(
        inner,  # type: ignore[arg-type]
        UsageRecorder(sink, FixedClock(NOW)),
        prompts=registry,
    )
    await gateway.complete(
        model="m",
        system="You are a helper.",
        messages=[],
        tools=[],
        max_tokens=10,
        tuning=LlmTuning(task=TASK),
    )
    assert inner.systems == ["You are a tutor."]
    [event] = sink.events
    assert event.prompt_version == 7
    assert event.prompt_hash is not None and len(event.prompt_hash) == 16


class Reader:
    async def calls(
        self, task: str | None, start: datetime, end: datetime
    ) -> list[PromptCallStats]:
        return [
            PromptCallStats(TASK, 2, 10, 1, 800.0, 2000.0, 100, 50, 3000),
            PromptCallStats(TASK, 0, 4, 0, 500.0, 900.0, 40, 20, 1000),
        ]

    async def ratings(
        self, task: str | None, start: datetime, end: datetime
    ) -> list[PromptRatingStats]:
        return [
            PromptRatingStats(TASK, 2, 4, 0.5),
            PromptRatingStats(TASK, 1, 2, -1.0),
        ]


async def test_analytics_joins_calls_and_ratings_per_version() -> None:
    rows = await PromptAnalytics(Reader()).report(ADMIN, TASK, NOW, NOW)
    assert [r.version for r in rows] == [0, 1, 2]
    built_in, rated_only, current = rows
    assert (built_in.calls, built_in.ratings, built_in.rating_average) == (4, 0, None)
    assert (rated_only.calls, rated_only.rating_average) == (0, -1.0)
    assert current.error_rate == pytest.approx(0.1)
    assert (current.p50_ms, current.p95_ms, current.cost_micro) == (800.0, 2000.0, 3000)
    assert (current.ratings, current.rating_average) == (4, 0.5)
