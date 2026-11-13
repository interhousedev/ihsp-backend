"""The honours rules (red diploma, gold and silver medal) Administration edits."""

from dataclasses import dataclass
from typing import Any

HONOURS_MAX_FOURS_LIMIT = 20


@dataclass(frozen=True, slots=True)
class FlagRule:
    """A rule without a parameter."""

    enabled: bool


@dataclass(frozen=True, slots=True)
class MaxFoursRule:
    """At most ``max`` semester marks of 4 (and none below 4)."""

    enabled: bool
    max: int


@dataclass(frozen=True, slots=True)
class SerialsRule:
    """The school certificate serial must be one of ``serials``."""

    enabled: bool
    serials: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HonoursRules:
    """Which rules count towards each award; the defaults are the lyceum's rules."""

    red_diploma_max_fours: MaxFoursRule = MaxFoursRule(True, 1)
    medal_certificate: SerialsRule = SerialsRule(True, ("TM-A", "TMA"))
    gold_controls_all_five: FlagRule = FlagRule(True)
    gold_semester_all_five: FlagRule = FlagRule(True)
    silver_controls_all_five: FlagRule = FlagRule(False)
    silver_semester_max_fours: MaxFoursRule = MaxFoursRule(True, 1)

    def as_stored(self) -> dict[str, Any]:
        """The JSON value kept under the ``honours`` platform setting."""
        return {
            "red_diploma_max_fours": _fours(self.red_diploma_max_fours),
            "medal_certificate": {
                "enabled": self.medal_certificate.enabled,
                "serials": list(self.medal_certificate.serials),
            },
            "gold_controls_all_five": {"enabled": self.gold_controls_all_five.enabled},
            "gold_semester_all_five": {"enabled": self.gold_semester_all_five.enabled},
            "silver_controls_all_five": {
                "enabled": self.silver_controls_all_five.enabled
            },
            "silver_semester_max_fours": _fours(self.silver_semester_max_fours),
        }


def _fours(rule: MaxFoursRule) -> dict[str, Any]:
    return {"enabled": rule.enabled, "max": rule.max}


__all__ = [
    "HONOURS_MAX_FOURS_LIMIT",
    "FlagRule",
    "HonoursRules",
    "MaxFoursRule",
    "SerialsRule",
]
