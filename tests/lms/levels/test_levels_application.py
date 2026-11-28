"""Level scheme handlers and LevelTracker with in-memory fakes (spec 2.5).

The implementation must provide `app.modules.lms.application.engagement.levels`:
  ListLevelSchemes(repo).execute(actor)
  CreateLevelScheme(repo, audit, access).execute(actor, scope, course_id, name, curve)
  -> scheme (inactive)
  UpdateTiers(repo, audit, access).execute(actor, scheme_id, tiers)       (validates)
  PreviewLevelScheme(repo, xp_totals, access).execute(actor, scheme_id) -> {"before":
  {lvl: n}, "after": {lvl: n}}
  ActivateLevelScheme(repo, audit, cache, access).execute(actor, scheme_id)
  `actor` is the real app.shared.actor.Actor. Platform schemes: Role.LMS_ADMIN only.
  Course schemes: `access.require_edit(actor, course_id)` (the course staff EDIT gate,
  scoped to ONE course; raises ForbiddenError) for create/update/preview/activate.
  ResolveScheme(repo).execute(course_id|None) -> course scheme else active platform
  scheme
  LevelTracker(repo_profiles, schemes, events).after_add_xp(user_id, course_id,
  total_xp)
and ports in `app.modules.lms.ports.level_scheme_repository`:
  LevelSchemeRepository: add, get, update, list, active_platform(),
  for_course(course_id),
    deactivate_platform(), activate(id)
  ProfileLevels: highest_level(user_id, course_id|None) -> int, set_highest(user_id,
  course_id|None, level)
    (separate high-water marks: platform (None) and one per course)
  XpTotals: all_totals() -> list[int]
Outbox event: 'lms.level_up' payload {user_id, level, tier_level_from, course_id}.
Authz: platform schemes LMS_ADMIN only (ForbiddenError otherwise); course schemes
need course staff EDIT. Boring choice: the fakes below are test-local.
"""

from typing import Any
from uuid import UUID, uuid4

from app.modules.lms.application.engagement.levels import (
    ActivateLevelScheme,
    CreateLevelScheme,
    LevelTracker,
    PreviewLevelScheme,
    ResolveScheme,
    UpdateTiers,
)
from app.modules.lms.domain.engagement.levels import (
    DEFAULT_SCHEME,
    Curve,
    LevelSchemeInvalidError,
    LevelTier,
)
from app.shared.actor import Actor as RealActor
from app.shared.actor import Role
from app.shared.base_error import ForbiddenError

import pytest

T = {"uz": "x", "ru": "x", "en": "x"}


def tier(n: int) -> LevelTier:
    return LevelTier(level_from=n, title=T, icon="star", color="#336699")


def Actor(admin: bool = True) -> RealActor:  # noqa: N802
    roles = {Role.LMS_ADMIN} if admin else {Role.TEACHER}
    return RealActor(user_id=uuid4(), roles=frozenset(roles))


class Access:
    """Course-scoped EDIT gate: `allowed=None` lets every course through."""

    def __init__(self, allowed: set[UUID] | None = None) -> None:
        self.allowed = allowed

    async def require_edit(self, actor: RealActor, course_id: UUID) -> None:
        if self.allowed is not None and course_id not in self.allowed:
            raise ForbiddenError()


ACCESS = Access()


class Repo:
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    async def add(self, s: Any) -> None:
        self.rows[s.id] = s

    async def get(self, id: UUID) -> Any:
        return self.rows.get(id)

    async def update(self, s: Any) -> None:
        self.rows[s.id] = s

    async def active_platform(self) -> Any:
        return next(
            (s for s in self.rows.values() if s.scope == "platform" and s.active),
            DEFAULT_SCHEME,
        )

    async def for_course(self, course_id: UUID) -> Any:
        return next(
            (s for s in self.rows.values() if s.course_id == course_id and s.active),
            None,
        )

    async def deactivate_platform(self) -> None:
        for s in self.rows.values():
            if s.scope == "platform":
                s.active = False

    async def activate(self, id: UUID) -> None:
        self.rows[id].active = True


class Audit:
    def __init__(self) -> None:
        self.rows: list[str] = []

    async def write(self, type: str, **kw: Any) -> None:
        self.rows.append(type)


class Cache:
    def __init__(self) -> None:
        self.busted = 0

    def bust(self) -> None:
        self.busted += 1


class Events:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, name: str, payload: dict[str, Any]) -> None:
        self.published.append((name, payload))


class Profiles:
    """High-water marks per (user, course|None); `highest` is the platform mark."""

    def __init__(self, highest: int = 1) -> None:
        self.marks: dict[UUID | None, int] = {None: highest}

    @property
    def highest(self) -> int:
        return self.marks[None]

    async def highest_level(self, user_id: UUID, course_id: UUID | None) -> int:
        return self.marks.get(course_id, 1)

    async def set_highest(
        self, user_id: UUID, course_id: UUID | None, level: int
    ) -> None:
        self.marks[course_id] = level


class Totals:
    def __init__(self, xps: list[int]) -> None:
        self.xps = xps

    async def all_totals(self) -> list[int]:
        return self.xps


async def _create(repo: Repo, actor: Actor, **kw: Any) -> Any:
    return await CreateLevelScheme(repo, Audit(), kw.get("access", ACCESS)).execute(
        actor,
        scope=kw.get("scope", "platform"),
        course_id=kw.get("course_id"),
        name=T,
        curve=kw.get("curve", Curve.quadratic(100)),
    )


async def test_create_makes_an_inactive_draft() -> None:
    repo = Repo()
    s = await _create(repo, Actor())
    assert s.active is False and repo.rows[s.id] is s


async def test_only_lms_admin_creates_platform_schemes() -> None:
    with pytest.raises(ForbiddenError):
        await _create(Repo(), Actor(admin=False))


async def test_update_tiers_validates_contiguity() -> None:
    repo, actor = Repo(), Actor()
    s = await _create(repo, actor)
    await UpdateTiers(repo, Audit(), ACCESS).execute(actor, s.id, [tier(1), tier(5)])
    assert [t.level_from for t in repo.rows[s.id].tiers] == [1, 5]
    with pytest.raises(LevelSchemeInvalidError):
        await UpdateTiers(repo, Audit(), ACCESS).execute(
            actor, s.id, [tier(2), tier(5)]
        )
    assert [t.level_from for t in repo.rows[s.id].tiers] == [1, 5]  # unchanged


async def test_preview_shows_distribution_before_and_after() -> None:
    repo, actor = Repo(), Actor()
    s = await _create(repo, actor, curve=Curve.quadratic(100))
    out = await PreviewLevelScheme(repo, Totals([0, 100, 350]), ACCESS).execute(
        actor, s.id
    )
    assert out.before == {1: 1, 2: 1, 3: 1}
    assert out.after == {1: 2, 2: 1}  # base 100: 200 xp for level 2
    assert repo.rows[s.id].active is False  # preview never activates


async def test_activate_swaps_the_platform_scheme_and_audits_and_busts_cache() -> None:
    repo, actor, audit, cache = Repo(), Actor(), Audit(), Cache()
    a, b = await _create(repo, actor), await _create(repo, actor)
    act = ActivateLevelScheme(repo, audit, cache, ACCESS)
    await act.execute(actor, a.id)
    await act.execute(actor, b.id)
    assert [s.active for s in (repo.rows[a.id], repo.rows[b.id])] == [False, True]
    assert sum(s.active for s in repo.rows.values()) == 1  # exactly one active
    assert len(audit.rows) == 2 and cache.busted == 2


async def test_activate_unknown_scheme_changes_nothing() -> None:
    repo, actor = Repo(), Actor()
    a = await _create(repo, actor)
    await ActivateLevelScheme(repo, Audit(), Cache(), ACCESS).execute(actor, a.id)
    with pytest.raises(LookupError):
        await ActivateLevelScheme(repo, Audit(), Cache(), ACCESS).execute(
            actor, uuid4()
        )
    assert repo.rows[a.id].active is True


async def test_resolve_prefers_course_scheme_then_platform_then_default() -> None:
    repo, actor, course = Repo(), Actor(), uuid4()
    assert await ResolveScheme(repo).execute(course) is DEFAULT_SCHEME
    p = await _create(repo, actor)
    await ActivateLevelScheme(repo, Audit(), Cache(), ACCESS).execute(actor, p.id)
    assert (await ResolveScheme(repo).execute(course)).id == p.id
    c = await _create(repo, actor, scope="course", course_id=course)
    await ActivateLevelScheme(repo, Audit(), Cache(), ACCESS).execute(actor, c.id)
    assert (await ResolveScheme(repo).execute(course)).id == c.id
    assert (await ResolveScheme(repo).execute(None)).id == p.id


async def test_activating_a_course_scheme_leaves_the_platform_one_active() -> None:
    repo, actor, course = Repo(), Actor(), uuid4()
    p = await _create(repo, actor)
    await ActivateLevelScheme(repo, Audit(), Cache(), ACCESS).execute(actor, p.id)
    c = await _create(repo, actor, scope="course", course_id=course)
    await ActivateLevelScheme(repo, Audit(), Cache(), ACCESS).execute(actor, c.id)
    assert repo.rows[p.id].active is True


async def test_tracker_emits_level_up_and_raises_highest() -> None:
    repo, events, profiles = Repo(), Events(), Profiles(1)
    user = uuid4()
    await LevelTracker(profiles, repo, events).after_add_xp(user, None, 120)
    assert profiles.highest == 2
    assert events.published == [
        (
            "lms.level_up",
            {"user_id": str(user), "level": 2, "tier_level_from": 1, "course_id": None},
        )
    ]


async def test_tracker_is_quiet_without_a_level_change() -> None:
    repo, events, profiles = Repo(), Events(), Profiles(2)
    await LevelTracker(profiles, repo, events).after_add_xp(uuid4(), None, 150)
    assert events.published == [] and profiles.highest == 2


async def test_tracker_never_demotes_when_a_harder_scheme_is_active() -> None:
    repo, actor, events, profiles = Repo(), Actor(), Events(), Profiles(4)
    s = await _create(repo, actor, curve=Curve.quadratic(1000))
    await ActivateLevelScheme(repo, Audit(), Cache(), ACCESS).execute(actor, s.id)
    await LevelTracker(profiles, repo, events).after_add_xp(uuid4(), None, 600)
    assert profiles.highest == 4 and events.published == []


async def test_tracker_fires_once_per_crossing() -> None:
    repo, events, profiles = Repo(), Events(), Profiles(1)
    t = LevelTracker(profiles, repo, events)
    user = uuid4()
    await t.after_add_xp(user, None, 120)
    await t.after_add_xp(user, None, 130)
    assert len(events.published) == 1


# ---- course-scoped authorization and per-scope high-water marks ---------------


async def test_course_staff_edits_their_course_only() -> None:
    repo, mine, other = Repo(), uuid4(), uuid4()
    teacher, access = Actor(admin=False), Access({mine})
    await _create(repo, teacher, scope="course", course_id=mine, access=access)
    with pytest.raises(ForbiddenError):
        await _create(repo, teacher, scope="course", course_id=other, access=access)


async def test_course_staff_cannot_touch_platform_schemes() -> None:
    repo, course = Repo(), uuid4()
    teacher = Actor(admin=False)
    with pytest.raises(ForbiddenError):
        await _create(repo, teacher, access=Access({course}))
    platform = await _create(repo, Actor())
    for call in (
        UpdateTiers(repo, Audit(), Access({course})).execute(
            teacher, platform.id, [tier(1)]
        ),
        ActivateLevelScheme(repo, Audit(), Cache(), Access({course})).execute(
            teacher, platform.id
        ),
        PreviewLevelScheme(repo, Totals([1]), Access({course})).execute(
            teacher, platform.id
        ),
    ):
        with pytest.raises(ForbiddenError):
            await call


async def test_course_staff_of_another_course_cannot_update_activate_or_preview() -> (
    None
):
    repo, mine, other = Repo(), uuid4(), uuid4()
    scheme = await _create(repo, Actor(), scope="course", course_id=mine)
    teacher, access = Actor(admin=False), Access({other})
    for call in (
        UpdateTiers(repo, Audit(), access).execute(teacher, scheme.id, [tier(1)]),
        ActivateLevelScheme(repo, Audit(), Cache(), access).execute(teacher, scheme.id),
        PreviewLevelScheme(repo, Totals([1]), access).execute(teacher, scheme.id),
    ):
        with pytest.raises(ForbiddenError):
            await call
    assert repo.rows[scheme.id].active is False


async def test_an_easy_course_scheme_does_not_suppress_the_platform_level_up() -> None:
    """Course and platform high-water marks are independent."""
    repo, events, profiles = Repo(), Events(), Profiles(1)
    easy, user = uuid4(), uuid4()
    course_scheme = await _create(
        repo, Actor(), scope="course", course_id=easy, curve=Curve.quadratic(10)
    )
    await ActivateLevelScheme(repo, Audit(), Cache(), ACCESS).execute(
        Actor(), course_scheme.id
    )
    t = LevelTracker(profiles, repo, events)
    await t.after_add_xp(user, easy, 400)  # high level under the easy course curve
    await t.after_add_xp(user, None, 120)  # platform curve: level 2, still celebrated
    levels = [(p["course_id"], p["level"]) for _, p in events.published]
    assert (None, 2) in levels
    assert profiles.marks[None] == 2 and profiles.marks[easy] > 2


async def test_two_courses_keep_separate_marks() -> None:
    repo, events, profiles = Repo(), Events(), Profiles(1)
    a, b, user = uuid4(), uuid4(), uuid4()
    t = LevelTracker(profiles, repo, events)
    await t.after_add_xp(user, a, 350)
    await t.after_add_xp(user, b, 120)
    assert profiles.marks[a] == 3 and profiles.marks[b] == 2
