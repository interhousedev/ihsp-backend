"""Level scheme use cases and the tracker that announces level-ups."""

import time
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.modules.lms.domain.engagement.errors import (
    LevelSchemeInvalidError,
    LevelSchemeNotFoundError,
)
from app.modules.lms.domain.engagement.levels import (
    DEFAULT_SCHEME,
    Curve,
    LevelScheme,
    LevelTier,
    Scope,
    apply_xp,
    distribution,
    level_of,
)
from app.modules.lms.ports.level_scheme_repository import (
    LevelSchemeRepository,
    ProfileLevels,
    XpTotals,
)
from app.shared.actor import Actor, Role

CACHE_SECONDS = 30.0


class CourseEditGate(Protocol):
    """The course staff `edit` gate of one course."""

    async def require_edit(self, actor: Actor, course_id: UUID) -> None:
        """Raise ForbiddenError unless the actor may edit the course."""
        ...


class LevelAudit(Protocol):
    """Writes the audit log."""

    async def write(self, type: str, **metadata: Any) -> None:
        """Record an entry."""
        ...


class SchemeCache(Protocol):
    """Drops cached schemes."""

    def bust(self) -> None:
        """Forget cached schemes."""
        ...


class LevelEvents(Protocol):
    """Publishes events of the lms."""

    async def publish(self, name: str, payload: dict[str, Any]) -> None:
        """Publish one event."""
        ...


async def _authorize(access: CourseEditGate, actor: Actor, scheme: LevelScheme) -> None:
    """Platform schemes belong to LMS admins, course schemes to the course editors."""
    if scheme.scope == "platform" or scheme.course_id is None:
        actor.require(Role.LMS_ADMIN)
    else:
        await access.require_edit(actor, scheme.course_id)


async def _load(repo: LevelSchemeRepository, id: UUID) -> LevelScheme:
    scheme = await repo.get(id)
    if scheme is None:
        raise LevelSchemeNotFoundError(params={"scheme_id": str(id)})
    return scheme


class ListLevelSchemes:
    """List every scheme (LMS admins)."""

    def __init__(self, repo: LevelSchemeRepository) -> None:
        """Store the repository."""
        self.repo = repo

    async def execute(self, actor: Actor) -> list[LevelScheme]:
        """Return the schemes."""
        actor.require(Role.LMS_ADMIN)
        return await self.repo.list()


class CreateLevelScheme:
    """Create an inactive draft scheme."""

    def __init__(
        self, repo: LevelSchemeRepository, audit: LevelAudit, access: CourseEditGate
    ) -> None:
        """Store collaborators."""
        self.repo = repo
        self.audit = audit
        self.access = access

    async def execute(
        self,
        actor: Actor,
        scope: Scope,
        course_id: UUID | None,
        name: dict[str, str],
        curve: Curve,
    ) -> LevelScheme:
        """Validate and store the scheme with the single default tier."""
        scheme = LevelScheme(
            id=uuid4(),
            scope=scope,
            course_id=course_id,
            name=name,
            curve=curve,
            tiers=list(DEFAULT_SCHEME.tiers),
            active=False,
        )
        await _authorize(self.access, actor, scheme)
        scheme.validate()
        await self.repo.add(scheme)
        await self.audit.write(
            "lms.level_scheme.created",
            actor_id=str(actor.user_id),
            scheme_id=str(scheme.id),
        )
        return scheme


class UpdateTiers:
    """Replace the tiers of a scheme."""

    def __init__(
        self, repo: LevelSchemeRepository, audit: LevelAudit, access: CourseEditGate
    ) -> None:
        """Store collaborators."""
        self.repo = repo
        self.audit = audit
        self.access = access

    async def execute(
        self, actor: Actor, scheme_id: UUID, tiers: list[LevelTier]
    ) -> LevelScheme:
        """Validate the tiers and store them; an invalid list changes nothing."""
        scheme = await _load(self.repo, scheme_id)
        await _authorize(self.access, actor, scheme)
        candidate = LevelScheme(
            scheme.id,
            scheme.scope,
            scheme.course_id,
            scheme.name,
            scheme.curve,
            list(tiers),
            scheme.active,
        )
        candidate.validate()
        await self.repo.update(candidate)
        await self.audit.write(
            "lms.level_scheme.tiers_updated",
            actor_id=str(actor.user_id),
            scheme_id=str(scheme.id),
        )
        return candidate


@dataclass(frozen=True, slots=True)
class LevelPreview:
    """Learners per level under both schemes; `probe` is (before, after) level."""

    before: dict[int, int]
    after: dict[int, int]
    probe: tuple[int, int] | None = None


class PreviewLevelScheme:
    """Show how learners would be spread over the levels before and after."""

    def __init__(
        self, repo: LevelSchemeRepository, totals: XpTotals, access: CourseEditGate
    ) -> None:
        """Store collaborators."""
        self.repo = repo
        self.totals = totals
        self.access = access

    async def execute(
        self, actor: Actor, scheme_id: UUID, xp: int | None = None
    ) -> LevelPreview:
        """Return the level distribution under the current scheme and this one.

        With `xp` the result also has `probe`: the level that XP total reaches
        under the current scheme (`before`) and under this one (`after`).
        """
        scheme = await _load(self.repo, scheme_id)
        await _authorize(self.access, actor, scheme)
        current = (
            await self.repo.for_course(scheme.course_id)
            if scheme.course_id is not None
            else None
        ) or await self.repo.active_platform()
        xps = await self.totals.all_totals()
        probe = (
            None
            if xp is None
            else (level_of(xp, current).level, level_of(xp, scheme).level)
        )
        return LevelPreview(
            before=distribution(xps, current),
            after=distribution(xps, scheme),
            probe=probe,
        )


class ActivateLevelScheme:
    """Make a scheme the live one of its platform or course."""

    def __init__(
        self,
        repo: LevelSchemeRepository,
        audit: LevelAudit,
        cache: SchemeCache,
        access: CourseEditGate,
    ) -> None:
        """Store collaborators."""
        self.repo = repo
        self.audit = audit
        self.cache = cache
        self.access = access

    async def execute(self, actor: Actor, scheme_id: UUID) -> LevelScheme:
        """Activate the scheme, replacing the previous live one of its scope."""
        scheme = await _load(self.repo, scheme_id)
        await _authorize(self.access, actor, scheme)
        if scheme.scope == "platform":
            await self.repo.deactivate_platform()
        await self.repo.activate(scheme.id)
        await self.audit.write(
            "lms.level_scheme.activated",
            actor_id=str(actor.user_id),
            scheme_id=str(scheme.id),
        )
        self.cache.bust()
        scheme.active = True
        return scheme


class AttachCourseScheme:
    """Make a course scheme the live one of its course (course editors)."""

    def __init__(
        self,
        repo: LevelSchemeRepository,
        activate: "ActivateLevelScheme",
        access: CourseEditGate,
    ) -> None:
        """Store collaborators."""
        self.repo = repo
        self.activate = activate
        self.access = access

    async def execute(
        self, actor: Actor, course_id: UUID, scheme_id: UUID
    ) -> LevelScheme:
        """Activate a scheme that was made for this course."""
        await self.access.require_edit(actor, course_id)
        scheme = await _load(self.repo, scheme_id)
        if scheme.scope != "course" or scheme.course_id != course_id:
            raise LevelSchemeInvalidError(params={"field": "scheme_id"})
        return await self.activate.execute(actor, scheme_id)


class ResolveScheme:
    """Pick the scheme in force: the course's, else the platform's, else the default."""

    def __init__(self, repo: LevelSchemeRepository) -> None:
        """Store the repository."""
        self.repo = repo

    async def execute(self, course_id: UUID | None) -> LevelScheme:
        """Return the scheme."""
        if course_id is not None:
            found = await self.repo.for_course(course_id)
            if found is not None:
                return found
        return await self.repo.active_platform()


class CachedLevelSchemes:
    """Reads the live schemes through a short cache; `bust` drops it."""

    def __init__(self, repo: LevelSchemeRepository) -> None:
        """Wrap the repository."""
        self.repo = repo
        self._platform: tuple[float, LevelScheme] | None = None
        self._courses: dict[UUID, tuple[float, LevelScheme | None]] = {}

    def bust(self) -> None:
        """Forget everything cached."""
        self._platform = None
        self._courses.clear()

    async def active_platform(self) -> LevelScheme:
        """Return the active platform scheme."""
        now = time.monotonic()
        if self._platform is None or now - self._platform[0] > CACHE_SECONDS:
            self._platform = (now, await self.repo.active_platform())
        return self._platform[1]

    async def for_course(self, course_id: UUID) -> LevelScheme | None:
        """Return the active course scheme."""
        now = time.monotonic()
        hit = self._courses.get(course_id)
        if hit is None or now - hit[0] > CACHE_SECONDS:
            hit = (now, await self.repo.for_course(course_id))
            self._courses[course_id] = hit
        return hit[1]


class LevelTracker:
    """After XP is added: raise the high-water mark and announce a level-up."""

    def __init__(
        self,
        profiles: ProfileLevels,
        schemes: Any,
        events: LevelEvents,
    ) -> None:
        """Store collaborators; `schemes` offers active_platform and for_course."""
        self.profiles = profiles
        self.schemes = schemes
        self.events = events

    async def after_add_xp(
        self, user_id: UUID, course_id: UUID | None, total_xp: int
    ) -> None:
        """Track the level of one scope: the course's, or the platform's for None.

        The total is the learner's XP in that scope, so the caller reports the
        platform total and each affected course total in separate calls.
        """
        scheme = (
            await self.schemes.for_course(course_id) if course_id is not None else None
        ) or await self.schemes.active_platform()
        highest = await self.profiles.highest_level(user_id, course_id)
        shown, new_highest, up = apply_xp(highest, total_xp, scheme)
        if new_highest != highest:
            await self.profiles.set_highest(user_id, course_id, new_highest)
        if not up:
            return
        tier = scheme.tier_of(shown)
        await self.events.publish(
            "lms.level_up",
            {
                "user_id": str(user_id),
                "level": shown,
                "tier_level_from": tier.level_from if tier else 1,
                "course_id": None if course_id is None else str(course_id),
            },
        )


class UserXp(Protocol):
    """A learner's XP on the platform or in one course."""

    async def user_total(self, user_id: UUID, course_id: UUID | None) -> int:
        """Return the total."""
        ...


class XpLevelHook:
    """Runs the tracker for the platform and every course a learner just earned in."""

    def __init__(self, tracker: LevelTracker, xp: UserXp) -> None:
        """Store collaborators."""
        self.tracker = tracker
        self.xp = xp

    async def after_xp(self, user_id: UUID, course_ids: set[UUID | None]) -> None:
        """Track the platform level and the level of each affected course."""
        scopes: list[UUID | None] = [None]
        scopes.extend(c for c in course_ids if c is not None)
        for course_id in scopes:
            await self.tracker.after_add_xp(
                user_id, course_id, await self.xp.user_total(user_id, course_id)
            )


@dataclass(frozen=True, slots=True)
class MyLevelView:
    """A learner's level in one scope under the scheme in force."""

    scope: Scope
    course_id: UUID | None
    xp_total: int
    level: int
    xp_into_level: int
    xp_for_next: int
    tier: LevelTier | None


class MyLevel:
    """The learner's own level on the platform or in one course."""

    def __init__(
        self, schemes: Any, profiles: ProfileLevels, xp: UserXp  # noqa: ANN401
    ) -> None:
        """Store collaborators; `schemes` offers active_platform and for_course."""
        self.schemes = schemes
        self.profiles = profiles
        self.xp = xp

    async def execute(self, actor: Actor, course_id: UUID | None) -> MyLevelView:
        """Return the level; it never drops below the highest one shown."""
        scheme = (
            await self.schemes.for_course(course_id) if course_id is not None else None
        ) or await self.schemes.active_platform()
        total = await self.xp.user_total(actor.user_id, course_id)
        highest = await self.profiles.highest_level(actor.user_id, course_id)
        derived = level_of(total, scheme)
        shown = max(derived.level, highest)
        if shown == derived.level:
            into, to_next = derived.xp_into_level, derived.xp_for_next
        else:
            into, to_next = 0, 0
        return MyLevelView(
            scope="platform" if course_id is None else "course",
            course_id=course_id,
            xp_total=total,
            level=shown,
            xp_into_level=into,
            xp_for_next=to_next,
            tier=scheme.tier_of(shown),
        )
