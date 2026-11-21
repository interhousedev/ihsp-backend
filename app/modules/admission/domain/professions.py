"""Professions (ISCO-08) with their GenAI exposure, and the ikigai answers.

The catalogue is a committed snapshot (`catalog_data/professions.json`, built
by `scripts/build_professions_snapshot.py`). Exposure is the ILO 2025 mean task
score of the occupation; risk and horizon are derived here, as scenarios.
"""

from dataclasses import dataclass, field
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.errors import (
    CharLimitError,
    InvalidAnswerError,
    ItemLimitError,
)

Risk = Literal["low", "medium", "high"]
Horizon = Literal["now", "5y", "10y+"]
SalaryBand = Literal["low", "medium", "high"]
LANGS: Final = ("en", "ru", "uz")

PROFESSIONS_MAX: Final = 5
IKIGAI_ITEMS_MAX: Final = 8
CHIP_MAX: Final = 60
SCORE_MAX: Final = 0.7
"""Highest occupation score of the ILO 2025 table (the exposure scale's top)."""
SUBSTITUTION: Final = 0.5
"""Share of automation among automation + augmentation when no usage data joins."""
LOW_BELOW: Final = 0.25
HIGH_ABOVE: Final = 0.5

MAJOR_GROUPS: Final[dict[str, dict[str, str]]] = {
    "1": {"en": "Managers", "ru": "Руководители", "uz": "Rahbarlar"},
    "2": {
        "en": "Professionals",
        "ru": "Специалисты высшего уровня квалификации",
        "uz": "Oliy malakali mutaxassislar",
    },
    "3": {
        "en": "Technicians and associate professionals",
        "ru": "Специалисты среднего уровня квалификации",
        "uz": "Oʻrta malakali mutaxassislar",
    },
}


def risk_value(score: float) -> float:
    """R = E x (0.5 + 0.5 S) with E the score over the scale maximum."""
    return (score / SCORE_MAX) * (0.5 + 0.5 * SUBSTITUTION)


def risk_of(score: float) -> Risk:
    """Band of the risk: low < 0.25, medium 0.25..0.5, high above."""
    r = risk_value(score)
    if r < LOW_BELOW:
        return "low"
    return "medium" if r <= HIGH_ABOVE else "high"


def horizon_of(score: float, gradient: str) -> Horizon:
    """Scenario, never a calendar year.

    `now`: the occupation's tasks are already uniformly exposed (gradient 4);
    `5y`: high risk or significant exposure (gradient 3); otherwise `10y+`.
    """
    if gradient.endswith("Gradient 4"):
        return "now"
    if gradient.endswith("Gradient 3") or risk_of(score) == "high":
        return "5y"
    return "10y+"


@dataclass(frozen=True, slots=True)
class Source:
    """A cited source of a profession's data."""

    label: str
    url: str


@dataclass(frozen=True, slots=True)
class Profession:
    """An ISCO-08 4-digit occupation of the snapshot."""

    id: str
    group: str
    names: dict[str, str]
    ai_exposure: float
    ai_risk: Risk
    horizon: Horizon
    related_fields: tuple[str, ...]
    salary_band: SalaryBand | None = None
    sources: tuple[Source, ...] = ()

    def name(self, locale: str) -> str:
        """Name in the locale; uz falls back to ru, anything else to en."""
        return self.names.get(locale) or self.names.get("ru") or self.names["en"]

    def matches(self, needle: str) -> bool:
        """True when the needle is part of any language's name or the id."""
        n = needle.strip().casefold()
        return (
            not n or n in self.id or any(n in v.casefold() for v in self.names.values())
        )


@dataclass(frozen=True, slots=True)
class ChosenProfession:
    """A profession the student ranked (1 = first choice)."""

    profession_id: str
    rank: int


@dataclass(frozen=True, slots=True)
class Ikigai:
    """Free-text chips of the four ikigai questions."""

    love: tuple[str, ...] = ()
    good_at: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    paid: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProfessionPlan:
    """One student's ranked professions and ikigai answers."""

    student_id: UUID
    chosen: tuple[ChosenProfession, ...] = ()
    ikigai: Ikigai = field(default_factory=Ikigai)


def clean_chips(name: str, raw: list[str]) -> tuple[str, ...]:
    """Trimmed, de-duplicated chips; too many or too long ones are refused."""
    out: list[str] = []
    for text in raw:
        t = " ".join(text.split())
        if not t:
            continue
        if len(t) > CHIP_MAX:
            raise CharLimitError(params={"field": name, "limit": CHIP_MAX})
        if t.casefold() not in {o.casefold() for o in out}:
            out.append(t)
    if len(out) > IKIGAI_ITEMS_MAX:
        raise ItemLimitError(
            params={"kind": f"ikigai_{name}", "limit": IKIGAI_ITEMS_MAX}
        )
    return tuple(out)


def clean_choice(
    items: list[tuple[str, int]], known: set[str]
) -> tuple[ChosenProfession, ...]:
    """At most five known professions, once each, ranked 1..n in the given order."""
    if len(items) > PROFESSIONS_MAX:
        raise ItemLimitError(params={"kind": "professions", "limit": PROFESSIONS_MAX})
    seen: set[str] = set()
    for pid, _ in items:
        if pid not in known or pid in seen:
            raise InvalidAnswerError(params={"question": "profession_id"})
        seen.add(pid)
    ordered = sorted(items, key=lambda it: it[1])
    return tuple(ChosenProfession(pid, i + 1) for i, (pid, _) in enumerate(ordered))
