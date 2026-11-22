"""Preference tags and university matching of the "discover" feature.

Tags are stable strings shared with the web (`prefs.tags.*` messages). A
university can only answer tags the catalog has data for; the others are left
out of the score instead of being guessed.
"""

import re
from collections.abc import Container, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from app.modules.admission.domain.admit_rate import (
    SAFETY_RATE,
    TARGET_RATE,
    admission_rate,
)
from app.modules.admission.domain.chooser import CatalogInstitution, budget_upper

Experience = Literal["academic", "social", "adventure", "holistic"]
Setting = Literal["rural", "suburban", "city"]
Budget = Literal["under_10k", "under_30k", "under_50k", "any"]
Decision = Literal["interested", "not_my_vibe"]
Status = Literal["safety", "target", "reach"]

EXPERIENCES: Final = ("academic", "social", "adventure", "holistic")
SETTINGS: Final = ("rural", "suburban", "city")
BUDGETS: Final = ("under_10k", "under_30k", "under_50k", "any")
DECISIONS: Final = ("interested", "not_my_vibe")
BUDGET_CAP: Final = {
    "under_10k": Decimal(10_000),
    "under_30k": Decimal(30_000),
    "under_50k": Decimal(50_000),
}
BOOL_TAGS: Final = (
    ("small_classes", "small_classes"),
    ("ec_important", "ec_important"),
    ("food_important", "food_important"),
    ("prestige", "prestige"),
    ("academics_first", "academics_first"),
    ("need_aid", "aid_needed"),
    ("cost_major", "cost_major"),
)
QUESTIONS: Final = 12
"""Number of questions; `completed` means all are answered."""
MAJOR_MAX: Final = 60
REGION_MAX: Final = 8
PRESTIGE_RATE: Final = 0.2
KNOWN_PREFIX: Final = "known:"
_DIMENSION: Final = {
    "budget": "budget",
    "setting": "setting",
    "major": "major",
    "prestige": "prestige",
    "academics_first": "prestige",
}
_CITY_TYPE: Final = {"urban": "city", "suburban": "suburban", "rural": "rural"}
_SLUG = re.compile(r"[^a-z0-9]+")
_MAJOR_KEYWORDS: Final = {
    "computer_science": {"computer", "computing", "informatics", "ai"},
    "data_science": {"data", "statistics", "computing", "ai"},
    "mathematics": {"mathematics", "statistics", "natural"},
    "physics": {"physics", "natural", "sciences", "science"},
    "chemistry": {"chemistry", "natural", "sciences", "science"},
    "biology": {"biology", "life", "natural", "sciences", "science"},
    "mechanical_engineering": {"engineering"},
    "electrical_engineering": {"engineering"},
    "civil_engineering": {"engineering", "built"},
    "medicine": {"medicine", "medical", "health", "dentistry"},
    "public_health": {"health", "medical", "nursing"},
    "economics": {"economics", "social", "administrative"},
    "business": {"business", "management"},
    "finance": {"business", "economics", "management"},
    "international_relations": {"social", "politics", "government", "law"},
    "political_science": {"social", "politics", "government"},
    "law": {"law"},
    "psychology": {"psychology", "social", "brain"},
    "linguistics": {"linguistics", "languages", "humanities", "english"},
    "history": {"history", "humanities", "classics", "arts"},
    "philosophy": {"philosophy", "humanities", "arts"},
    "architecture": {"architecture", "built", "design"},
    "design": {"design", "arts"},
    "music": {"music", "arts"},
}
"""Career major code → words of a catalog field that satisfy it (the catalog lists
broad fields such as "Engineering" or "Natural sciences")."""


@dataclass(frozen=True, slots=True)
class PreferenceAnswers:
    """What the student said about the university they want; all optional."""

    experience: Experience | None = None
    setting: tuple[Setting, ...] | None = None
    region: tuple[str, ...] | None = None
    small_classes: bool | None = None
    ec_important: bool | None = None
    food_important: bool | None = None
    major: str | None = None
    prestige: bool | None = None
    academics_first: bool | None = None
    need_aid: bool | None = None
    budget: Budget | None = None
    cost_major: bool | None = None

    @property
    def answered(self) -> int:
        """How many of the 13 questions have an answer."""
        return sum(getattr(self, f) is not None for f in self.__dataclass_fields__)

    @property
    def completed(self) -> bool:
        """Whether every question is answered."""
        return self.answered >= QUESTIONS


def slug(text: str) -> str:
    """Lowercase ascii slug of a free text (`Computer Science` → `computer-science`)."""
    return _SLUG.sub("-", text.casefold()).strip("-")


def _tuple(value: object, allowed: Container[str] | None = None) -> tuple[str, ...]:
    """Unique strings of a stored list (a legacy plain string is one element)."""
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list | tuple):
        return ()
    kept = (v for v in items if isinstance(v, str) and v.casefold() != "any")
    return tuple(dict.fromkeys(v for v in kept if allowed is None or v in allowed))


def answers_from_stored(raw: Mapping[str, object]) -> PreferenceAnswers:
    """Answers from the stored JSON.

    Legacy shapes (`"any"`, a string, `distance`) are read as the multi-select
    lists and unknown keys are ignored.
    """
    known = {k: v for k, v in raw.items() if k in _STORED_FIELDS}
    if "setting" in known:
        known["setting"] = _tuple(known["setting"], SETTINGS)
    if "region" in known:
        known["region"] = tuple(
            r.strip().upper() for r in _tuple(known["region"]) if r.strip()
        )
    return PreferenceAnswers(**known)  # type: ignore[arg-type]


_STORED_FIELDS: Final = frozenset(PreferenceAnswers.__dataclass_fields__)


def preference_tags(a: PreferenceAnswers) -> list[str]:
    """The stable tags of the answers, in a fixed order, without duplicates."""
    tags: list[str] = []
    if a.budget:
        tags.append(f"budget:{a.budget}")
    if a.setting:
        tags.extend(f"setting:{s}" for s in a.setting)
    if a.region:
        tags.extend(f"region:{r}" for r in a.region)
    if a.experience:
        tags.append(f"experience:{a.experience}")
    tags.extend(tag for attr, tag in BOOL_TAGS if getattr(a, attr) is True)
    if a.major and (m := a.major.strip().casefold()):
        tags.append(f"major:{m}")
    return tags


def cost_usd(inst: CatalogInstitution) -> Decimal | None:
    """Yearly cost of attendance in USD, when known."""
    if inst.coa_total is None or inst.coa_currency != "USD":
        return None
    return inst.coa_total


def status_of(rate: float | None) -> Status | None:
    """Safety, target or reach from the admission rate."""
    if rate is None:
        return None
    if rate >= SAFETY_RATE:
        return "safety"
    return "target" if rate >= TARGET_RATE else "reach"


def _profile_tags(inst: CatalogInstitution) -> list[str]:
    tags: list[str] = []
    city_type = inst.fact("city_type")
    if city_type is not None and str(city_type.value) in _CITY_TYPE:
        tags.append(f"setting:{_CITY_TYPE[str(city_type.value)]}")
        tags.append(f"{KNOWN_PREFIX}setting")
    for f in inst.fields:
        if s := slug(f):
            tags.extend((f"major:{s}", f"major:{s.replace('-', '_')}"))
            tags.append(f"{KNOWN_PREFIX}major")
            words = set(s.split("-"))
            tags.extend(
                f"major:{code}"
                for code, keywords in _MAJOR_KEYWORDS.items()
                if words & keywords
            )
    return tags


def _rate_and_aid_tags(inst: CatalogInstitution) -> list[str]:
    tags: list[str] = []
    rate = admission_rate(inst)
    if rate is not None:
        tags.append(f"{KNOWN_PREFIX}prestige")
        if rate <= PRESTIGE_RATE:
            tags.extend(("prestige", "academics_first"))
    if inst.aid_basis in ("need_based", "need_blind", "need_aware") or (
        inst.merit_available or inst.scholarship_count > 0
    ):
        tags.append("aid_needed")
    return tags


def budget_fit(
    band: str | None, net: Decimal | None, gross: Decimal | None
) -> Literal["fits", "above"] | None:
    """Whether the yearly price fits the student's budget band; None if unknown.

    The net price (after the average aid) is used when known, else the sticker one.
    An open band (`over_50k`) always fits.
    """
    price = net if net is not None else gross
    if not band or price is None:
        return None
    upper = budget_upper(band)
    return "fits" if upper is None or price <= upper else "above"


def university_tags(inst: CatalogInstitution) -> list[str]:
    """Tags a university satisfies, plus `known:<dimension>` for the data it has."""
    tags = ["budget:any"]
    cost = cost_usd(inst)
    if cost is not None:
        tags.append(f"{KNOWN_PREFIX}budget")
    for key, cap in BUDGET_CAP.items():
        if cost is not None and cost <= cap:
            tags.append(f"budget:{key}")
    tags.append(f"region:{inst.country}")
    tags.extend(_profile_tags(inst))
    return list(dict.fromkeys(tags + _rate_and_aid_tags(inst)))


def _evaluable(tag: str) -> bool:
    return tag.split(":", 1)[0] in {
        "budget",
        "setting",
        "region",
        "major",
        "prestige",
        "academics_first",
        "aid_needed",
    }


@dataclass(frozen=True, slots=True)
class Overlap:
    """Matched tags out of the evaluable preference tags."""

    count: int
    total: int
    tags: tuple[str, ...]


def _known(tag: str, have: set[str]) -> bool:
    """Whether the university has data for the tag's dimension."""
    dim = _DIMENSION.get(tag.split(":", 1)[0])
    if dim is None or tag == "budget:any":
        return True
    return f"{KNOWN_PREFIX}{dim}" in have


def _dimension_key(tag: str) -> str:
    """Setting and region tags are alternatives: meeting any one meets the answer."""
    prefix = tag.split(":", 1)[0]
    return prefix if prefix in ("setting", "region") else tag


def match(pref_tags: Sequence[str], uni_tags: Iterable[str]) -> tuple[int, Overlap]:
    """Percentage (0..100) and overlap of the preference answers a university meets."""
    have = set(uni_tags)
    asked = [t for t in pref_tags if _evaluable(t) and _known(t, have)]
    hit = tuple(t for t in asked if t in have)
    total = len({_dimension_key(t) for t in asked})
    count = len({_dimension_key(t) for t in hit})
    pct = round(100 * count / total) if total else 0
    return pct, Overlap(count, total, hit)
