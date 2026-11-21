"""Chances of one student at one institution: deterministic factors and a curve.

Pure. The status (safety, target or reach) starts from the published acceptance
rate and moves one step with the academic fit. Nothing is computed from a null
fact: a factor without data is `unknown`. Values of the simulation are on a
common scale: `gpa` is the percent of the student's grading scale (0..100),
`score` is the SAT total (400..1600); `chance` is a percentage (0..100).
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from app.modules.admission.domain.admit_rate import (
    SAFETY_RATE,
    TARGET_RATE,
    admission_rate,
)
from app.modules.admission.domain.budget import cost_after_aid
from app.modules.admission.domain.chooser import (
    CatalogInstitution,
    budget_upper,
)
from app.modules.admission.domain.estimates import LOW_RATE
from app.modules.admission.domain.matching import cost_usd

Status = Literal["safety", "target", "reach"]
Level = Literal["strong", "ok", "weak", "unknown"]
Metric = Literal["gpa", "score"]
Param = str | int | float
STATUSES: Final[Sequence[Status]] = ("reach", "target", "safety")

PERCENT_MIN: Final = 10.0
"""An undeclared median above this is a percent; below it the scale is unknown."""
OK_MARGIN: Final = 5.0
"""Percent of the scale below the median that still counts as a fair fit."""
SCORE_MAX: Final = 1600
SCORE_MIN: Final = 400
GPA_SCALE: Final = 4.0
SCORE_SCALE: Final = 50.0
"""Width of the logistic curve in simulation units (points of percent, SAT)."""
STRONG_ACTIVITIES: Final = 6
OK_ACTIVITIES: Final = 3
STRONG_ADVANCED: Final = 4
COST_STRETCH: Final = 1.5
"""A cost up to this multiple of the budget is workable with aid."""
_ADVANCED = re.compile(
    r"\b(ap|ib|hl|a[- ]?level|advanced|honou?rs|olympiad|olimpiada|олимпиада)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Action:
    """Where the student can improve the factor."""

    kind: str
    href: str


@dataclass(frozen=True, slots=True)
class Factor:
    """One judged dimension; `detail` carries the numbers the web renders."""

    key: str
    level: Level
    detail: dict[str, Param] = field(default_factory=dict)
    action: Action | None = None


@dataclass(frozen=True, slots=True)
class Simulation:
    """Chance (percent) along the student's metric, around the institution's median."""

    metric: Metric
    your_value: float | None
    median: float | None
    threshold: float | None
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class Chances:
    """Status, the reason key, the factors and the curve."""

    status: Status | None
    summary_key: str
    factors: tuple[Factor, ...]
    simulation: Simulation


@dataclass(frozen=True, slots=True)
class Preferences:
    """The student's stated preferences that matter here; None when unanswered."""

    budget: str | None = None
    region: tuple[str, ...] | None = None
    need_aid: bool | None = None


@dataclass(frozen=True, slots=True)
class StudentData:
    """What is known about the student; None or zero when nothing was entered."""

    gpa_ratio: float | None = None
    sat_total: float | None = None
    activities: int = 0
    honors: int = 0
    course_titles: Sequence[str] = ()
    course_levels: Sequence[str | None] = ()
    budget_band: str | None = None
    prefs: Preferences = Preferences()


def _fact_number(
    inst: CatalogInstitution, *keys: str, usd_only: bool = False
) -> float | None:
    for key in keys:
        f = inst.fact(key)
        if f is None:
            continue
        if (
            usd_only
            and isinstance(f.value, dict)
            and f.value.get("currency", "USD") != "USD"
        ):
            continue
        v = f.value.get("value") if isinstance(f.value, dict) else f.value
        if isinstance(v, bool) or not isinstance(v, int | float):
            continue
        if v > 0:
            return float(v)
    return None


def _expected_gpa(rate: float | None) -> float | None:
    """Typical admitted GPA (percent of scale) implied by the rate."""
    if rate is None:
        return None
    for ceiling, value in ((0.1, 95.0), (0.25, 90.0), (0.5, 85.0), (0.75, 80.0)):
        if rate <= ceiling:
            return value
    return 75.0


def _median_gpa(
    inst: CatalogInstitution, rate: float | None
) -> tuple[float | None, bool]:
    for key in ("median_gpa", "gpa_median"):
        f = inst.fact(key)
        if f is None:
            continue
        v = f.value.get("value") if isinstance(f.value, dict) else f.value
        scale = f.value.get("scale") if isinstance(f.value, dict) else None
        if isinstance(v, bool) or not isinstance(v, int | float) or v <= 0:
            continue
        if isinstance(scale, int | float) and not isinstance(scale, bool):
            if scale > 0 and v <= scale:
                return v / scale * 100, False
        elif PERCENT_MIN < v <= 100:
            return float(v), False
    return _expected_gpa(rate), True


def _academics(
    inst: CatalogInstitution, st: StudentData, rate: float | None
) -> tuple[Factor, Simulation]:
    sat_median = _fact_number(inst, "median_sat", "sat_median")
    use_score = st.sat_total is not None and sat_median is not None
    metric: Metric
    if use_score:
        metric = "score"
        mine, median, estimated = st.sat_total, sat_median, False
        unit = 100 / SCORE_MAX
    else:
        metric = "gpa"
        median, estimated = _median_gpa(inst, rate)
        mine = st.gpa_ratio * 100 if st.gpa_ratio is not None else None
        unit = 1.0
    sim = _simulate(metric, mine, median, rate)
    if mine is None or median is None:
        detail: dict[str, Param] = {"metric": metric}
        if median is not None:
            detail["median"] = round(median, 1)
        grades = None if st.gpa_ratio is not None else Action("add_grades", "/setup")
        return Factor("academics", "unknown", detail, grades), sim
    delta = (mine - median) * unit
    level: Level = "strong" if delta >= 0 else "ok" if delta >= -OK_MARGIN else "weak"
    detail = {
        "metric": metric,
        "yours": round(mine, 1),
        "median": round(median, 1),
        "delta": round(mine - median, 1),
        "estimated": int(estimated),
    }
    action = Action("raise_score", "/tests") if level == "weak" else None
    return Factor("academics", level, detail, action), sim


def _logistic(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def _simulate(
    metric: Metric, mine: float | None, median: float | None, rate: float | None
) -> Simulation:
    if median is None:
        return Simulation(metric, mine, None, None, ())
    base = min(0.95, max(0.02, rate if rate is not None else 0.3))
    scale = SCORE_SCALE if metric == "score" else GPA_SCALE
    logit = math.log(base / (1 - base))

    def chance(x: float) -> float:
        return round(100 * _logistic(logit + (x - median) / scale), 1)

    if metric == "score":
        lo, hi, step = max(SCORE_MIN, median - 200), min(SCORE_MAX, median + 100), 25.0
    else:
        lo, hi, step = max(0.0, median - 16), min(100.0, median + 8), 2.0
    pts: list[tuple[float, float]] = []
    x = float(math.floor(lo / step) * step)
    while x <= hi:
        if x >= lo - step:
            pts.append((x, chance(x)))
        x += step
    threshold: float | None = median - scale * logit
    if threshold is not None and not lo <= threshold <= hi:
        threshold = None
    return Simulation(
        metric,
        round(mine, 1) if mine is not None else None,
        round(median, 1),
        round(threshold, 1) if threshold is not None else None,
        tuple(pts),
    )


def _rigor(st: StudentData) -> Factor:
    total = len(st.course_titles)
    if total == 0:
        return Factor("course_rigor", "unknown", {}, Action("add_courses", "/courses"))
    advanced = sum(
        1
        for t, lv in zip(st.course_titles, st.course_levels, strict=True)
        if _ADVANCED.search(f"{t} {lv or ''}")
    )
    level: Level = (
        "strong" if advanced >= STRONG_ADVANCED else "ok" if advanced >= 1 else "weak"
    )
    action = Action("add_courses", "/courses") if level != "strong" else None
    return Factor("course_rigor", level, {"advanced": advanced, "total": total}, action)


def _cost(inst: CatalogInstitution, st: StudentData) -> Factor:
    cost = cost_usd(inst)
    cost_n = (
        float(cost)
        if cost is not None
        else (
            _fact_number(inst, "intl_coa_usd", usd_only=True)
            if inst.coa_total is None
            else None
        )
    )
    net = cost_after_aid(cost, "USD", inst.aid_profile) if cost is not None else None
    if net is not None:
        cost_n = float(net)
    band = st.prefs.budget or st.budget_band
    upper = _budget_upper(band)
    open_band = band == "any" or (band or "").startswith("over_")
    if cost_n is None or (upper is None and not open_band):
        detail: dict[str, Param] = {}
        if cost_n is not None:
            detail["cost"] = round(cost_n)
        return Factor(
            "cost", "unknown", detail, Action("set_budget", "/chooser/?step=quiz")
        )
    detail = {"cost": round(cost_n)}
    if upper is None:
        return Factor("cost", "strong", detail)
    detail["budget"] = round(upper)
    detail["gap"] = max(0, round(cost_n - upper))
    aid = bool(inst.merit_available) or (inst.aid_basis or "").startswith("need")
    if cost_n <= upper:
        level: Level = "strong"
    elif aid and cost_n <= upper * COST_STRETCH:
        level = "ok"
    else:
        level = "weak"
    detail["aid"] = int(aid)
    return Factor("cost", level, detail)


def _budget_upper(band: str | None) -> float | None:
    upper = budget_upper(band)
    return float(upper) if upper is not None else None


def _location(inst: CatalogInstitution, st: StudentData) -> Factor:
    regions = st.prefs.region
    if regions is None:
        return Factor(
            "location",
            "unknown",
            {"country": inst.country},
            Action("set_region", "/chooser/search/?prefs=1"),
        )
    if not regions:
        return Factor("location", "ok", {"country": inst.country})
    same = inst.country.casefold() in {r.casefold() for r in regions}
    return Factor(
        "location",
        "strong" if same else "weak",
        {"country": inst.country, "region": ",".join(regions)},
        None if same else Action("set_region", "/chooser/search/?prefs=1"),
    )


def _activities(st: StudentData) -> Factor:
    n = st.activities
    level: Level = (
        "strong" if n >= STRONG_ACTIVITIES else "ok" if n >= OK_ACTIVITIES else "weak"
    )
    action = Action("add_activities", "/activities") if level != "strong" else None
    return Factor("activities", level, {"count": n, "honors": st.honors}, action)


def _status_no_rate(academics: Level) -> tuple[Status | None, str]:
    if academics == "unknown":
        return None, "unknown_data"
    if academics == "weak":
        return "reach", "reach_academics"
    return "target", "target_balanced"


def _status(rate: float | None, academics: Level) -> tuple[Status | None, str]:
    if rate is None:
        return _status_no_rate(academics)
    base = 2 if rate >= SAFETY_RATE else 1 if rate >= TARGET_RATE else 0
    step = base
    if academics == "weak":
        step -= 1
    elif academics == "strong" and rate * 100 >= LOW_RATE:
        step += 1
    step = max(0, min(2, step))
    if rate * 100 < LOW_RATE:
        step = 0
    status: Status = STATUSES[step]
    return status, _status_key(status, academics, rate, step > base)


def _status_key(status: Status, academics: Level, rate: float, raised: bool) -> str:
    if status == "reach":
        if academics == "weak":
            return "reach_academics"
        return "reach_selective" if rate * 100 < LOW_RATE else "reach_rate"
    if status == "safety":
        return "safety_strong"
    return (
        "target_strong_academics"
        if academics == "strong" and raised
        else "target_balanced"
    )


def evaluate(inst: CatalogInstitution, st: StudentData) -> Chances:
    """Judge the factors, the status and the curve of one institution."""
    rate = admission_rate(inst)
    academics, sim = _academics(inst, st, rate)
    status, key = _status(rate, academics.level)
    factors = (
        academics,
        _rigor(st),
        _cost(inst, st),
        _location(inst, st),
        _activities(st),
    )
    return Chances(status, key, factors, sim)
