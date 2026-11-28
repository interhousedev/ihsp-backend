"""Composition of the level schemes and the XP hook that announces level-ups."""

from dataclasses import dataclass

from app.modules.lms.application.engagement.level_access import (
    AuditLevelEvents,
    CourseEditGate,
)
from app.modules.lms.application.engagement.levels import (
    ActivateLevelScheme,
    AttachCourseScheme,
    CachedLevelSchemes,
    CreateLevelScheme,
    LevelTracker,
    ListLevelSchemes,
    MyLevel,
    PreviewLevelScheme,
    UpdateTiers,
    XpLevelHook,
)
from app.modules.lms.application.learning.types import UowFactory
from app.modules.lms.infrastructure.level_repository import (
    SqlLevelSchemes,
    SqlProfileLevels,
    SqlXpTotals,
)
from app.shared.wiring import ModuleDeps


@dataclass(frozen=True, slots=True)
class LevelServices:
    """The level scheme use cases and the XP hook."""

    list_schemes: ListLevelSchemes
    create: CreateLevelScheme
    update_tiers: UpdateTiers
    preview: PreviewLevelScheme
    activate: ActivateLevelScheme
    attach: AttachCourseScheme
    hook: XpLevelHook
    me: MyLevel


def build_levels(deps: ModuleDeps, uow_factory: UowFactory) -> LevelServices:
    """Return the level services over the lms schema."""
    schemes = SqlLevelSchemes(deps.sessionmaker)
    totals = SqlXpTotals(deps.sessionmaker)
    cache = CachedLevelSchemes(schemes)
    gate = CourseEditGate(uow_factory)
    audit = AuditLevelEvents(uow_factory)
    activate = ActivateLevelScheme(schemes, audit, cache, gate)
    profiles = SqlProfileLevels(deps.sessionmaker)
    tracker = LevelTracker(profiles, cache, audit)
    return LevelServices(
        list_schemes=ListLevelSchemes(schemes),
        create=CreateLevelScheme(schemes, audit, gate),
        update_tiers=UpdateTiers(schemes, audit, gate),
        preview=PreviewLevelScheme(schemes, totals, gate),
        activate=activate,
        attach=AttachCourseScheme(schemes, activate, gate),
        hook=XpLevelHook(tracker, totals),
        me=MyLevel(cache, profiles, totals),
    )
