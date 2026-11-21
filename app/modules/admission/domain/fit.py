"""University fit: four axes (afford, goals, profile, traits) from known facts.

Every axis is 0..100 or None when its data is missing; nothing is computed from
null facts. The total is the weighted mean of the known axes only.

Preference ratings (1..10, "how much it matters") become the axis weights:
afford <- price; goals <- salary + ai_resilience; profile <- academics +
prestige; traits <- social + city + home; then normalised to sum 1. A student
who never saved ratings gets the research defaults 0.25/0.30/0.30/0.15.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from functools import cache
from typing import Final, Literal

from app.modules.admission.domain.budget import cost_after_aid
from app.modules.admission.domain.chooser import CatalogInstitution, budget_upper
from app.modules.admission.domain.fit_copy import msg
from app.modules.admission.domain.professions import Profession
from app.modules.admission.domain.study_fields import FIELDS, canonical_id, labels_of

AxisKey = Literal["afford", "goals", "profile", "traits"]
AXES: Final[tuple[AxisKey, ...]] = ("afford", "goals", "profile", "traits")
RATING_KEYS: Final = (
    "price",
    "salary",
    "ai_resilience",
    "prestige",
    "academics",
    "social",
    "city",
    "home",
)
RATING_MIN, RATING_MAX, RATING_DEFAULT = 1, 10, 5
DEFAULT_WEIGHTS: Final[dict[str, float]] = {
    "afford": 0.25,
    "goals": 0.30,
    "profile": 0.30,
    "traits": 0.15,
}
_NO_DATA_GAIN: Final = 50
"""Gain shown for a step that would turn an unknown axis into a known one."""
_NEIGHBOURS: Final = frozenset({"KZ", "KG", "TJ", "TM", "AF"})
_MID: Final = frozenset({"TR", "RU", "AE", "IN", "CN", "KR", "GE", "AZ", "SA"})
_RISK: Final = {"low": 1.0, "medium": 0.7, "high": 0.4}
_PAY: Final = {"low": 0.6, "medium": 0.8, "high": 1.0}
_SETTING_FIT: Final = {"urban": 1.0, "suburban": 0.6, "rural": 0.3}


def default_ratings() -> dict[str, int]:
    """Every rating at 5."""
    return dict.fromkeys(RATING_KEYS, RATING_DEFAULT)


def weights_of(ratings: dict[str, int]) -> dict[str, float]:
    """Axis weights from ratings (see the module docstring), summing to 1."""
    r = {k: ratings.get(k, RATING_DEFAULT) for k in RATING_KEYS}
    raw = {
        "afford": r["price"],
        "goals": r["salary"] + r["ai_resilience"],
        "profile": r["academics"] + r["prestige"],
        "traits": r["social"] + r["city"] + r["home"],
    }
    total = sum(raw.values())
    return {k: round(v / total, 4) for k, v in raw.items()}


@dataclass(frozen=True, slots=True)
class Raise:
    """A step that moves an axis; `gain` is the axis points it could add."""

    label: str
    href: str
    gain: int


@dataclass(frozen=True, slots=True)
class AxisFit:
    """One axis of one list entry."""

    key: AxisKey
    score: int | None
    weight: float
    why: tuple[str, ...]
    raises: tuple[Raise, ...] = ()


@dataclass(frozen=True, slots=True)
class FitResult:
    """The four axes and the total over the known ones."""

    total: int | None
    axes: tuple[AxisFit, ...]


@dataclass(frozen=True, slots=True)
class StudentFit:
    """What is known about the student."""

    ratings: dict[str, int] = field(default_factory=default_ratings)
    budget_band: str | None = None
    professions: tuple[Profession, ...] = ()
    """Chosen professions, best first."""
    focus_fields: tuple[str, ...] = ()
    has_scores: bool = False


@dataclass(frozen=True, slots=True)
class EntryFit:
    """What is known about one list entry."""

    institution: CatalogInstitution
    estimate: str = "unknown"
    """`safety`, `target`, `reach` or `unknown`."""


@cache
def _group_of() -> dict[str, str]:
    return {f.id: f.group for f in FIELDS}


def _clamp(x: float) -> int:
    return max(0, min(100, round(x)))


def _usd(x: Decimal) -> str:
    return f"${int(x):,}"


def _field_ids(inst: CatalogInstitution) -> set[str]:
    return {canonical_id(f) for f in inst.fields}


def _afford(s: StudentFit, e: EntryFit, loc: str, weight: float) -> AxisFit:
    inst = e.institution
    cost = inst.coa_total if inst.coa_currency == "USD" else None
    if not s.budget_band:
        return AxisFit(
            "afford",
            None,
            weight,
            (msg(loc, "afford.no_budget"),),
            (Raise(msg(loc, "raise.afford.budget"), "/chooser/budget", _NO_DATA_GAIN),),
        )
    if cost is None:
        return AxisFit("afford", None, weight, (msg(loc, "afford.no_cost"),))
    aid = cost_after_aid(cost, "USD", inst.aid_profile)
    net = aid if aid is not None else cost
    why: list[str] = []
    upper = budget_upper(s.budget_band)
    if upper is None:
        score, why = 100, [msg(loc, "afford.open", net=_usd(net))]
    elif net <= upper:
        score = 100
        why = [msg(loc, "afford.within", net=_usd(net), budget=_usd(upper))]
    else:
        score = _clamp(100 * (2 - float(net / upper)))
        why = [msg(loc, "afford.over", net=_usd(net), budget=_usd(upper))]
    if aid is None:
        why.append(msg(loc, "afford.sticker"))
    raises: tuple[Raise, ...] = ()
    if score < 100:
        raises = (
            Raise(msg(loc, "raise.afford.aid"), "/chooser/scholarships", 100 - score),
        )
    return AxisFit("afford", score, weight, tuple(why), raises)


def _goals(s: StudentFit, e: EntryFit, loc: str, weight: float) -> AxisFit:
    inst_fields = _field_ids(e.institution)
    pick = Raise(msg(loc, "raise.goals.pick"), "/career", _NO_DATA_GAIN)
    if not inst_fields:
        return AxisFit("goals", None, weight, (msg(loc, "goals.no_fields"),))
    if not s.professions:
        if not s.focus_fields:
            return AxisFit("goals", None, weight, (msg(loc, "goals.field"),), (pick,))
        hit = [f for f in s.focus_fields if f in inst_fields]
        score = _clamp(100 * len(hit) / len(s.focus_fields))
        why = [msg(loc, "goals.field")]
        return AxisFit("goals", score, weight, tuple(why), (pick,))
    n = len(s.professions)
    weights = [1 / (i + 1) for i in range(n)]
    matched: list[tuple[Profession, str]] = []
    cover = 0.0
    for w, p in zip(weights, s.professions, strict=True):
        common = [f for f in p.related_fields if f in inst_fields]
        if common:
            cover += w
            matched.append((p, common[0]))
    base = 100 * cover / sum(weights)
    if not matched:
        return AxisFit(
            "goals", _clamp(base), weight, (msg(loc, "goals.none"),), (pick,)
        )
    why = [
        msg(
            loc,
            "goals.match",
            fields=labels_of(matched[0][1], matched[0][1], loc),
            profession=matched[0][0].name(loc),
        )
    ]
    ai = s.ratings.get("ai_resilience", 5) / 10
    risk = sum(_RISK[p.ai_risk] for p, _ in matched) / len(matched)
    factor = 1 - ai * 0.3 * (1 - risk)
    banded = [p.salary_band for p, _ in matched if p.salary_band is not None]
    if banded:
        pay = sum(_PAY[b] for b in banded) / len(banded)
        factor *= 1 - (s.ratings.get("salary", 5) / 10) * 0.3 * (1 - pay)
        why.append(msg(loc, "goals.salary", band=msg(loc, f"band.{banded[0]}")))
    why.append(msg(loc, "goals.risk", risk=msg(loc, f"risk.{matched[0][0].ai_risk}")))
    score = _clamp(base * factor)
    return AxisFit(
        "goals", score, weight, tuple(why[:3]), (pick,) if base < 100 else ()
    )


def _profile(s: StudentFit, e: EntryFit, loc: str, weight: float) -> AxisFit:
    inst = e.institution
    parts: list[float] = []
    why: list[str] = []
    raises: list[Raise] = []
    inst_fields = _field_ids(inst)
    if s.focus_fields and inst_fields:
        hit = [f for f in s.focus_fields if f in inst_fields]
        groups = {_group_of().get(f) for f in inst_fields}
        if hit:
            parts.append(100)
            why.append(
                msg(loc, "profile.fields_yes", fields=labels_of(hit[0], hit[0], loc))
            )
        elif any(_group_of().get(f) in groups for f in s.focus_fields):
            parts.append(60)
            why.append(msg(loc, "profile.fields_group"))
        else:
            parts.append(25)
            why.append(msg(loc, "profile.fields_no"))
    elif not s.focus_fields:
        raises.append(Raise(msg(loc, "raise.profile.fields"), "/career", 10))
    chance = {"safety": 90, "target": 70, "reach": 40}.get(e.estimate)
    if chance is not None:
        parts.append(chance)
        why.append(msg(loc, f"profile.{e.estimate}"))
    policy = inst.fact("test_policy")
    if policy is not None and str(policy.value) == "required" and not s.has_scores:
        parts = [p * 0.7 for p in parts] or [40]
        why.append(msg(loc, "profile.tests_missing"))
        raises.append(Raise(msg(loc, "raise.profile.tests"), "/tests", 15))
    if not parts:
        return AxisFit(
            "profile", None, weight, (msg(loc, "profile.no_data"),), tuple(raises)
        )
    return AxisFit(
        "profile",
        _clamp(sum(parts) / len(parts)),
        weight,
        tuple(why[:3]),
        tuple(raises),
    )


def _distance(country: str) -> tuple[float, str]:
    if country == "UZ":
        return 1.0, "same"
    if country in _NEIGHBOURS:
        return 0.7, "near"
    if country in _MID:
        return 0.5, "mid"
    return 0.25, "far"


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _acceptance_rate(inst: CatalogInstitution) -> float | None:
    """Percent admitted: the international rate first, a range by its minimum."""
    for key in ("intl_acceptance_rate", "acceptance_rate"):
        f = inst.fact(key)
        if f is None:
            continue
        v = f.value
        rate = _num(v.get("min") if isinstance(v, dict) else v)
        if rate is not None:
            return rate
    return None


def _traits(s: StudentFit, e: EntryFit, loc: str, weight: float) -> AxisFit:
    inst = e.institution
    r = s.ratings
    comps: list[tuple[int, float, str]] = []  # (importance, fit 0..1, line)
    city = inst.fact("city_type")
    if city is not None and str(city.value) in _SETTING_FIT:
        v = str(city.value)
        comps.append(
            (
                r.get("city", 5),
                _SETTING_FIT[v],
                msg(loc, "traits.city", setting=msg(loc, f"setting.{v}")),
            )
        )
    near, key = _distance(inst.country)
    comps.append(
        (
            r.get("home", 5),
            near,
            msg(loc, "traits.home", distance=msg(loc, f"distance.{key}")),
        )
    )
    rate = _acceptance_rate(inst)
    if rate is not None:
        sel = 1.0 if rate < 10 else 0.8 if rate < 25 else 0.55 if rate < 50 else 0.3
        comps.append(
            (r.get("prestige", 5), sel, msg(loc, "traits.prestige", rate=round(rate)))
        )
    share_fact = inst.fact("intl_share")
    share = _num(share_fact.value) if share_fact is not None else None
    if share is not None:
        comm = 1.0 if share >= 15 else 0.7 if share >= 8 else 0.4
        comps.append(
            (r.get("social", 5), comm, msg(loc, "traits.social", share=round(share)))
        )
    rate_step = Raise(
        msg(loc, "raise.traits.rate"), "/colleges/discover", _NO_DATA_GAIN
    )
    total_w = sum(w for w, _, _ in comps)
    if not comps or total_w == 0:
        return AxisFit(
            "traits", None, weight, (msg(loc, "traits.no_data"),), (rate_step,)
        )
    score = sum(w * 100 * (1 - (w / 10) * (1 - f)) for w, f, _ in comps) / total_w
    worst_first = sorted(comps, key=lambda c: (c[0] / 10) * (1 - c[1]), reverse=True)
    return AxisFit(
        "traits", _clamp(score), weight, tuple(c[2] for c in worst_first[:3])
    )


def compute_fit(
    student: StudentFit,
    entry: EntryFit,
    weights: dict[str, float],
    locale: str,
) -> FitResult:
    """The axes and the total of one entry; the total skips unknown axes."""
    axes = (
        _afford(student, entry, locale, weights["afford"]),
        _goals(student, entry, locale, weights["goals"]),
        _profile(student, entry, locale, weights["profile"]),
        _traits(student, entry, locale, weights["traits"]),
    )
    known = [a for a in axes if a.score is not None]
    wsum = sum(a.weight for a in known)
    if not known or wsum == 0:
        return FitResult(None, axes)
    total = sum((a.score or 0) * a.weight for a in known) / wsum
    return FitResult(_clamp(total), axes)
