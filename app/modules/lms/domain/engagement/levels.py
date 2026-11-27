"""Level schemes: how total XP turns into a level, and the tiers that name levels."""

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.modules.lms.domain.engagement.errors import LevelSchemeInvalidError
from app.modules.lms.domain.engagement.xp import Level

LOCALES = ("uz", "ru", "en")
Scope = Literal["platform", "course"]
MAX_LEVELS = 1_000


@dataclass(frozen=True, slots=True)
class Curve:
    """XP needed per level: `base * L * (L - 1)` or an explicit cumulative table."""

    kind: Literal["quadratic", "table"]
    base: int = 0
    steps: tuple[int, ...] = ()

    @classmethod
    def quadratic(cls, base: int) -> "Curve":
        """Return the quadratic curve `base * L * (L - 1)`."""
        return cls("quadratic", base=base)

    @classmethod
    def table(cls, steps: list[int]) -> "Curve":
        """Return a table of the cumulative XP of levels 2, 3, ... (the last caps)."""
        return cls("table", steps=tuple(steps))

    def xp_to_reach(self, level: int) -> int:
        """Return the total XP at which a level starts (level 1 starts at 0)."""
        if level <= 1:
            return 0
        if self.kind == "quadratic":
            return self.base * level * (level - 1)
        return self.steps[level - 2]

    def max_level(self) -> int | None:
        """Return the last level of a table, None for the open quadratic curve."""
        return len(self.steps) + 1 if self.kind == "table" else None

    def validate(self) -> None:
        """Raise LevelSchemeInvalidError for a curve that cannot rank anyone."""
        if self.kind == "quadratic":
            if self.base <= 0:
                raise LevelSchemeInvalidError(params={"field": "curve.base"})
            return
        steps = self.steps
        ok = (
            0 < len(steps) <= MAX_LEVELS
            and steps[0] > 0
            and all(a < b for a, b in zip(steps, steps[1:], strict=False))
        )
        if not ok:
            raise LevelSchemeInvalidError(params={"field": "curve.table"})


@dataclass(frozen=True, slots=True)
class LevelTier:
    """A named band of levels starting at `level_from`."""

    level_from: int
    title: dict[str, str]
    icon: str
    color: str
    reward_badge_id: UUID | None = None


def _all_locales(texts: dict[str, str]) -> bool:
    return all(texts.get(locale, "").strip() for locale in LOCALES)


@dataclass(slots=True)
class LevelScheme:
    """A curve plus tiers, for the whole platform or one course."""

    id: UUID
    scope: Scope
    course_id: UUID | None
    name: dict[str, str]
    curve: Curve
    tiers: list[LevelTier]
    active: bool = field(default=False)

    def validate(self) -> None:
        """Raise LevelSchemeInvalidError when any part is unusable."""
        if (self.scope == "course") != (self.course_id is not None):
            raise LevelSchemeInvalidError(params={"field": "course_id"})
        if not _all_locales(self.name):
            raise LevelSchemeInvalidError(params={"field": "name"})
        self.curve.validate()
        self.validate_tiers()

    def validate_tiers(self) -> None:
        """Tiers start at level 1, ascend strictly; each ends where the next starts."""
        starts = [t.level_from for t in self.tiers]
        if not starts or starts[0] != 1:
            raise LevelSchemeInvalidError(params={"field": "tiers"})
        if any(a >= b for a, b in zip(starts, starts[1:], strict=False)):
            raise LevelSchemeInvalidError(params={"field": "tiers"})
        if not all(_all_locales(t.title) for t in self.tiers):
            raise LevelSchemeInvalidError(params={"field": "tiers.title"})

    def tier_of(self, level: int) -> LevelTier | None:
        """Return the tier covering a level."""
        starts = [t.level_from for t in self.tiers]
        index = bisect_right(starts, level) - 1
        return self.tiers[index] if index >= 0 else None


DEFAULT_SCHEME = LevelScheme(
    id=UUID(int=0),
    scope="platform",
    course_id=None,
    name={"uz": "Standart", "ru": "Стандартная", "en": "Default"},
    curve=Curve.quadratic(50),
    tiers=[
        LevelTier(
            level_from=1,
            title={"uz": "Daraja", "ru": "Уровень", "en": "Level"},
            icon="star",
            color="#336699",
        )
    ],
    active=True,
)


def level_of(xp: int, scheme: LevelScheme) -> Level:
    """Return the level of a total under a scheme."""
    curve = scheme.curve
    cap = curve.max_level()
    level = 1
    while (cap is None or level < cap) and curve.xp_to_reach(level + 1) <= xp:
        level += 1
    start = curve.xp_to_reach(level)
    if cap is not None and level >= cap:
        return Level(level=level, xp_into_level=xp - start, xp_for_next=0)
    return Level(
        level=level,
        xp_into_level=xp - start,
        xp_for_next=curve.xp_to_reach(level + 1) - start,
    )


def apply_xp(highest_level: int, xp: int, scheme: LevelScheme) -> tuple[int, int, bool]:
    """Return (level shown, new highest level, leveled up); never demotes."""
    derived = level_of(xp, scheme).level
    shown = max(derived, highest_level)
    return shown, shown, shown > highest_level


def distribution(xps: list[int], scheme: LevelScheme) -> dict[int, int]:
    """Return how many learners sit at each level."""
    counts: dict[int, int] = {}
    for xp in xps:
        level = level_of(xp, scheme).level
        counts[level] = counts.get(level, 0) + 1
    return dict(sorted(counts.items()))
