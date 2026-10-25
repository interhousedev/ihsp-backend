"""The limits in force: overrides, cache, extensions and staff (no database)."""

from datetime import date
from uuid import UUID, uuid4

from app.settings import LimitsSettings
from app.shared.actor import Actor, Role
from app.shared.limits import (
    EffectiveLimits,
    LimitExtension,
    LimitSnapshot,
    StaticLimits,
    is_unlimited,
    is_unlimited_roles,
)

TODAY = date(2026, 10, 11)
BASE = LimitsSettings()


class Ticks:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Storage:
    """The snapshot the loader returns; counts the reads and can fail."""

    def __init__(self, snapshot: LimitSnapshot | None = None) -> None:
        self.snapshot = snapshot or LimitSnapshot()
        self.reads = 0
        self.fail = False

    async def load(self) -> LimitSnapshot:
        self.reads += 1
        if self.fail:
            raise RuntimeError("database is down")
        return self.snapshot


def provider(
    storage: Storage,
    ticks: Ticks | None = None,
    roles: dict[UUID, frozenset[Role]] | None = None,
) -> EffectiveLimits:
    async def roles_of(user_id: UUID) -> frozenset[Role]:
        return (roles or {}).get(user_id, frozenset({Role.STUDENT}))

    return EffectiveLimits(
        BASE,
        storage.load,
        today=lambda: TODAY,
        roles=roles_of,
        monotonic=ticks or Ticks(),
    )


def student(user_id: UUID | None = None) -> Actor:
    return Actor(user_id=user_id or uuid4(), roles=frozenset({Role.STUDENT}))


def teacher() -> Actor:
    return Actor(user_id=uuid4(), roles=frozenset({Role.TEACHER}))


async def test_an_override_applies_and_a_reset_gives_the_environment_value() -> None:
    storage = Storage(LimitSnapshot(overrides={"ai_daily_tokens_student": 1000}))
    limits = provider(storage)

    assert (await limits.current()).ai_daily_tokens_student == 1000

    storage.snapshot = LimitSnapshot()
    limits.invalidate()

    assert (
        await limits.current()
    ).ai_daily_tokens_student == BASE.ai_daily_tokens_student


async def test_the_snapshot_is_cached_for_its_ttl_and_then_read_again() -> None:
    storage = Storage()
    ticks = Ticks()
    limits = provider(storage, ticks)

    await limits.current()
    ticks.now = 29.0
    await limits.current()
    assert storage.reads == 1

    ticks.now = 31.0
    await limits.current()
    assert storage.reads == 2


async def test_invalidate_drops_the_cache_at_once() -> None:
    storage = Storage()
    limits = provider(storage)

    await limits.current()
    limits.invalidate()
    await limits.current()

    assert storage.reads == 2


async def test_a_failed_read_keeps_the_last_good_snapshot() -> None:
    storage = Storage(LimitSnapshot(overrides={"nb_chat_per_minute": 40}))
    ticks = Ticks()
    limits = provider(storage, ticks)
    assert (await limits.current()).nb_chat_per_minute == 40

    storage.fail = True
    ticks.now = 31.0

    assert (await limits.current()).nb_chat_per_minute == 40


async def test_staff_are_unlimited_for_quotas_and_still_rate_limited() -> None:
    limits = provider(Storage())

    view = await limits.for_actor(teacher())

    assert view.unlimited is True
    assert view.ai_daily_tokens_student is None
    assert view.nb_artifacts_per_day is None
    assert view.web_search_per_day_staff is None
    assert view.lms_ai_chat_per_minute == BASE.lms_ai_chat_per_minute
    assert view.ai_max_tool_steps == BASE.ai_max_tool_steps


async def test_a_student_extension_multiplies_the_quotas_of_that_student_only() -> None:
    chosen = uuid4()
    storage = Storage(LimitSnapshot(extensions={chosen: LimitExtension(multiplier=3)}))
    limits = provider(storage)

    extended = await limits.for_user(chosen, unlimited=False)
    other = await limits.for_user(uuid4(), unlimited=False)

    assert extended.ai_daily_tokens_student == 3 * BASE.ai_daily_tokens_student
    assert other.ai_daily_tokens_student == BASE.ai_daily_tokens_student


async def test_explicit_extension_values_are_a_floor_and_never_a_cut() -> None:
    chosen = uuid4()
    raise_floor = LimitExtension(values={"nb_daily_tokens_student": 9_000_000})
    cut_attempt = LimitExtension(values={"nb_daily_tokens_student": 1000})
    limits = provider(Storage(LimitSnapshot(extensions={chosen: raise_floor})))
    assert (
        await limits.for_user(chosen, unlimited=False)
    ).nb_daily_tokens_student == 9_000_000

    limits = provider(Storage(LimitSnapshot(extensions={chosen: cut_attempt})))
    assert (
        await limits.for_user(chosen, unlimited=False)
    ).nb_daily_tokens_student == BASE.nb_daily_tokens_student


async def test_an_extension_stops_after_its_expiry_date() -> None:
    chosen = uuid4()
    expired = LimitExtension(multiplier=5, expires_on=date(2026, 10, 10))
    still_on = LimitExtension(multiplier=5, expires_on=TODAY)

    limits = provider(Storage(LimitSnapshot(extensions={chosen: expired})))
    assert (
        await limits.for_user(chosen, unlimited=False)
    ).ai_daily_tokens_student == BASE.ai_daily_tokens_student

    limits = provider(Storage(LimitSnapshot(extensions={chosen: still_on})))
    assert (
        await limits.for_user(chosen, unlimited=False)
    ).ai_daily_tokens_student == 5 * BASE.ai_daily_tokens_student


async def test_an_override_and_an_extension_combine_as_the_larger_value() -> None:
    chosen = uuid4()
    doubled = LimitSnapshot(
        overrides={"ai_daily_tokens_student": 1_000_000},
        extensions={chosen: LimitExtension(multiplier=2)},
    )
    floor_below_override = LimitSnapshot(
        overrides={"nb_daily_tokens_student": 300_000},
        extensions={
            chosen: LimitExtension(values={"nb_daily_tokens_student": 150_000})
        },
    )
    floor_above_override = LimitSnapshot(
        overrides={"nb_daily_tokens_student": 100_000},
        extensions={
            chosen: LimitExtension(values={"nb_daily_tokens_student": 150_000})
        },
    )

    assert (
        await provider(Storage(doubled)).for_user(chosen, unlimited=False)
    ).ai_daily_tokens_student == 2_000_000
    assert (
        await provider(Storage(floor_below_override)).for_user(chosen, unlimited=False)
    ).nb_daily_tokens_student == 300_000
    assert (
        await provider(Storage(floor_above_override)).for_user(chosen, unlimited=False)
    ).nb_daily_tokens_student == 150_000


async def test_a_multiplier_does_not_scale_hours_or_sizes() -> None:
    chosen = uuid4()
    limits = provider(
        Storage(LimitSnapshot(extensions={chosen: LimitExtension(multiplier=5)}))
    )

    view = await limits.for_user(chosen, unlimited=False)

    assert view.ai_session_hours == BASE.ai_session_hours
    assert view.ai_text_max_bytes == BASE.ai_text_max_bytes


async def test_an_extension_does_not_lift_a_staff_quota() -> None:
    staff = uuid4()
    limits = provider(
        Storage(LimitSnapshot(extensions={staff: LimitExtension(multiplier=3)})),
        roles={staff: frozenset({Role.TEACHER})},
    )

    view = await limits.for_user(staff, unlimited=None)

    assert view.ai_daily_tokens_student is None


async def test_the_roles_decide_staff_when_the_caller_does_not_say() -> None:
    lecturer, pupil = uuid4(), uuid4()
    limits = provider(
        Storage(),
        roles={lecturer: frozenset({Role.TEACHER}), pupil: frozenset({Role.STUDENT})},
    )

    assert (await limits.for_user(lecturer)).nb_daily_tokens_student is None
    assert (
        await limits.for_user(pupil)
    ).nb_daily_tokens_student == BASE.nb_daily_tokens_student


async def test_a_static_provider_treats_nobody_as_staff_unless_told() -> None:
    limits = StaticLimits(BASE)
    user = uuid4()

    assert (
        await limits.for_user(user)
    ).nb_daily_tokens_student == BASE.nb_daily_tokens_student
    assert (await limits.for_user(user, unlimited=True)).nb_daily_tokens_student is None


def test_staff_are_every_role_but_student() -> None:
    assert is_unlimited_roles([]) is True
    assert is_unlimited_roles([Role.STUDENT]) is False
    assert is_unlimited_roles([Role.STUDENT, Role.LIBRARIAN]) is True
    assert (
        is_unlimited(Actor(user_id=uuid4(), roles=frozenset({Role.LMS_CREATOR})))
        is True
    )
