"""Preference tags and university matching of the "discover" feature.

Tags are stable strings shared with the web (`prefs.tags.*` messages). A
university can only answer tags the catalog has data for; the others are left
out of the score instead of being guessed.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from app.modules.admission.domain.admit_rate import (
    SAFETY_RATE,
    TARGET_RATE,
    admission_rate,
)
from app.modules.admission.domain.chooser import CatalogInstitution

Experience = Literal["academic", "social", "adventure", "holistic"]
Setting = Literal["rural", "suburban", "city"]
Distance = Literal["any", "near", "far"]
Budget = Literal["under_10k", "under_30k", "under_50k", "any"]
Decision = Literal["interested", "not_my_vibe"]
Status = Literal["safety", "target", "reach"]

EXPERIENCES: Final = ("academic", "social", "adventure", "holistic")
SETTINGS: Final = ("rural", "suburban", "city")
DISTANCES: Final = ("any", "near", "far")
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
QUESTIONS: Final = 13
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
    setting: Setting | None = None
    region: str | None = None
    distance: Distance | None = None
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


def _region_tag(region: str) -> str:
    code = region.strip()
    return "region:any" if code.casefold() in ("", "any") else f"region:{code}"


def preference_tags(a: PreferenceAnswers) -> list[str]:
    """The stable tags of the answers, in a fixed order, without duplicates."""
    tags: list[str] = []
    if a.budget:
        tags.append(f"budget:{a.budget}")
    if a.setting:
        tags.append(f"setting:{a.setting}")
    if a.region:
        tags.append(_region_tag(a.region))
    if a.distance:
        tags.append(f"distance:{a.distance}")
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


def university_tags(inst: CatalogInstitution) -> list[str]:
    """Tags a university satisfies, plus `known:<dimension>` for the data it has."""
    tags = ["budget:any", "region:any", "distance:any"]
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
        "distance",
        "major",
        "prestige",
        "academics_first",
        "aid_needed",
    } and tag not in ("distance:near", "distance:far")


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


def match(pref_tags: Sequence[str], uni_tags: Iterable[str]) -> tuple[int, Overlap]:
    """Percentage (0..100) and overlap of the preference tags a university meets."""
    have = set(uni_tags)
    asked = [t for t in pref_tags if _evaluable(t) and _known(t, have)]
    hit = tuple(t for t in asked if t in have)
    pct = round(100 * len(hit) / len(asked)) if asked else 0
    return pct, Overlap(len(hit), len(asked), hit)
