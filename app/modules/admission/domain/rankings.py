"""University rankings and experience ratings shown on a match card.

Pure rules: which ranking subjects a student's fields and professions point at,
which stored rankings are relevant, and the map link of an institution.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final
from urllib.parse import quote_plus

from app.modules.admission.domain.study_fields import group_of

SYSTEMS: Final = ("qs", "the", "arwu", "usnews")
EXPERIENCE_KEYS: Final = ("social", "research", "work")
MAX_SHOWN: Final = 2
MAPS_QUERY: Final = "{query}"
DEFAULT_MAPS_TEMPLATE: Final = "https://www.google.com/maps/search/?api=1&query={query}"

_GROUP_SUBJECTS: Final[dict[str, tuple[str, ...]]] = {
    "computer_data": ("computer_science",),
    "engineering": ("engineering",),
    "business_economics": ("business", "economics"),
    "natural_sciences": ("natural_sciences",),
    "life_health": ("medicine", "life_sciences"),
    "social_sciences": ("social_sciences",),
    "law_politics": ("law", "politics"),
    "humanities": ("arts_humanities",),
    "arts_design": ("arts_humanities",),
    "architecture_planning": ("architecture",),
    "education": ("education",),
    "environment": ("environment",),
}
_FIELD_SUBJECTS: Final[dict[str, tuple[str, ...]]] = {
    "data_science": ("computer_science", "mathematics"),
    "mathematics": ("mathematics",),
    "physics": ("physics",),
    "chemistry": ("chemistry",),
    "economics": ("economics",),
    "management": ("business",),
    "business": ("business",),
    "taxation": ("business", "economics"),
    "biomedical_engineering": ("engineering", "medicine"),
    "chemical_engineering": ("engineering", "chemistry"),
    "medicine": ("medicine",),
    "biology": ("life_sciences",),
    "psychology": ("psychology",),
    "law": ("law",),
    "politics": ("politics",),
}


def subjects_for(field_ids: Iterable[str]) -> tuple[str, ...]:
    """Ranking subjects of study-field ids, best first (earlier fields first)."""
    out: list[str] = []
    for fid in field_ids:
        found = _FIELD_SUBJECTS.get(fid) or _GROUP_SUBJECTS.get(group_of(fid), ())
        out.extend(s for s in found if s not in out)
    return tuple(out)


def _order(item: Mapping[str, Any]) -> tuple[int, float]:
    system = item.get("system")
    rank = item.get("rank")
    return (
        SYSTEMS.index(system) if system in SYSTEMS else len(SYSTEMS),
        float(rank) if isinstance(rank, int | float) else float("inf"),
    )


def relevant_rankings(
    value: Any, subjects: Sequence[str], limit: int = MAX_SHOWN
) -> list[dict[str, Any]]:
    """The overall ranking first, then the best ranking of each relevant subject.

    The overall ranking (QS preferred) is shown whenever stored; subject
    rankings follow, most relevant subject first, up to `limit` in total.
    """
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    overall = [
        x for x in value if isinstance(x, dict) and x.get("subject") == "overall"
    ]
    if overall:
        out.append(min(overall, key=_order))
    for subject in subjects:
        if len(out) >= limit:
            break
        if subject == "overall":
            continue
        rows = [x for x in value if isinstance(x, dict) and x.get("subject") == subject]
        if rows:
            out.append(min(rows, key=_order))
    return out


def experience_meters(value: Any, locale: str) -> list[dict[str, Any]]:
    """`[{key, score, note}]` for the stored ratings 1..5; missing ones are left out."""
    if not isinstance(value, dict):
        return []
    notes = value.get("notes") if isinstance(value.get("notes"), dict) else {}
    out: list[dict[str, Any]] = []
    for key in EXPERIENCE_KEYS:
        score = value.get(key)
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            continue
        per = notes.get(key) if isinstance(notes, dict) else None
        note = (per.get(locale) or per.get("en")) if isinstance(per, dict) else None
        out.append({"key": key, "score": score, "note": note or None})
    return out


def valid_maps_template(value: object) -> bool:
    """An https URL template with exactly one `{query}` placeholder."""
    return (
        isinstance(value, str)
        and value.startswith("https://")
        and value.count(MAPS_QUERY) == 1
        and len(value) <= 300
        and not any(c.isspace() or ord(c) < 32 for c in value)
    )


def map_url(
    name: str,
    city: str | None,
    country: str,
    *,
    override: str | None = None,
    template: str | None = None,
) -> str:
    """The institution's own link, else the template (default Google Maps) filled."""
    if override:
        return override
    chosen = template if valid_maps_template(template) else DEFAULT_MAPS_TEMPLATE
    query = quote_plus(", ".join(x for x in (name, city, country) if x))
    return str(chosen).replace(MAPS_QUERY, query)
