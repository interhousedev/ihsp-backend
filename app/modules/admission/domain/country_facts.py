"""Country facts a student weighs when choosing where to study (the F3 contract).

One row per ISO country holds `facts`: a map of fact key to
`{score, values, text, sources}`. Score 5 is always best for the student (cheap, safe,
easy, many opportunities). A fact with a score or numbers must cite a source.
"""

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from urllib.parse import urlparse
from uuid import UUID

from app.modules.admission.domain.countries import COUNTRIES
from app.modules.admission.domain.study_fields import canonical_id, group_of
from app.shared.base_error import ValidationFailedError

CountryStatus = Literal["draft", "verified"]
COUNTRY_STATUSES: Final[tuple[str, ...]] = ("draft", "verified")

FACT_KEYS: Final[tuple[str, ...]] = (
    "cost_of_living",
    "climate",
    "opportunities",
    "student_visa",
    "safety",
    "bureaucracy",
    "travel_reach",
    "transport",
    "work_rights",
    "post_study",
    "language",
    "flights_tashkent",
    "community",
    "health",
    "aid",
    "tolerance",
    "employers",
    "salaries",
)
"""Every fact a country may carry; coverage is the share of these that are filled."""

OPPORTUNITY_FIELDS: Final[tuple[str, ...]] = (
    "cs_it",
    "engineering",
    "business_econ",
    "medicine_bio",
    "natural_sci",
    "social_law",
    "arts_media",
    "education_hum",
)
"""Keys of `opportunities.values`, each scored 1-5."""

REGIONS: Final[dict[str, tuple[str, ...]]] = {
    "central_asia": ("AM", "AZ", "GE", "KG", "KZ", "TJ", "TM", "UZ"),
    "europe": tuple(
        "AD AL AT BA BE BG BY CH CY CZ DE DK EE ES FI FR GB GR HR HU IE IS IT LI "
        "LT LU LV MC MD ME MK MT NL NO PL PT RO RS RU SE SI SK SM UA VA XK".split()
    ),
    "middle_east": tuple("AE BH IL IQ IR JO KW LB OM PS QA SA SY TR YE".split()),
    "asia": tuple(
        "AF BD BN BT CN ID IN JP KH KP KR LA LK MM MN MV MY NP PH PK SG TH TL "
        "VN".split()
    ),
    "africa": tuple(
        "AO BF BI BJ BW CD CF CG CI CM CV DJ DZ EG ER ET GA GH GM GN GQ GW KE KM "
        "LR LS LY MA MG ML MR MU MW MZ NA NE NG RW SC SD SL SN SO SS ST SZ TD TG "
        "TN TZ UG ZA ZM ZW".split()
    ),
    "americas": tuple(
        "AG AR BB BO BR BS BZ CA CL CO CR CU DM DO EC GD GT GY HN HT JM KN LC MX "
        "NI PA PE PY SR SV TT US UY VC VE".split()
    ),
    "oceania": tuple("AU FJ FM KI MH NR NZ PG PW SB TO TV VU WS".split()),
}
"""World region of every offered country, for the student country list filter."""

REGION_OF: Final[dict[str, str]] = {
    code: region for region, codes in REGIONS.items() for code in codes
}

EMPLOYERS_MAX: Final = 12
EMPLOYER_NAME_MAX: Final = 120
EMPLOYER_SECTOR_MAX: Final = 80
SALARY_MAX: Final = 10_000_000

GROUP_TO_OPPORTUNITY_FIELD: Final[dict[str, str]] = {
    "computer_data": "cs_it",
    "engineering": "engineering",
    "architecture_planning": "engineering",
    "business_economics": "business_econ",
    "life_health": "medicine_bio",
    "natural_sciences": "natural_sci",
    "environment": "natural_sci",
    "social_sciences": "social_law",
    "law_politics": "social_law",
    "arts_design": "arts_media",
    "humanities": "education_hum",
    "education": "education_hum",
}
"""Study-field group id (`study_fields.GROUPS`) → the opportunities key."""

LOCALES: Final[tuple[str, ...]] = ("en", "ru", "uz")
TEXT_MAX: Final = 1500
VALUE_STR_MAX: Final = 300
VALUES_MAX: Final = 24
SOURCES_MAX: Final = 8
URL_MAX: Final = 500
_AS_OF = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SCORED_VALUES: Final[dict[str, tuple[str, ...]]] = {
    "opportunities": OPPORTUNITY_FIELDS,
    "transport": ("domestic_rail", "domestic_bus", "domestic_air", "international"),
    "community": ("uzbek_diaspora", "halal"),
}
"""Value names that must be integers 1-5 per fact key."""


def opportunity_fields_of(field_names: list[str]) -> list[str]:
    """The distinct opportunity keys of a student's study fields, in input order."""
    out: list[str] = []
    for name in field_names:
        key = GROUP_TO_OPPORTUNITY_FIELD.get(group_of(canonical_id(name), name))
        if key is not None and key not in out:
            out.append(key)
    return out


@dataclass(frozen=True, slots=True)
class CountryFacts:
    """The stored facts of one country."""

    country: str
    as_of: str
    facts: dict[str, dict[str, Any]]
    status: CountryStatus
    verified_by: UUID | None = None
    updated_at: dt.datetime | None = None
    seeded: bool = field(default=False)


def is_country(code: str) -> bool:
    """Whether `code` is an offered ISO country code."""
    return code in COUNTRIES


def _bad(name: str) -> ValidationFailedError:
    return ValidationFailedError(params={"field": name})


def _clean_text(raw: Any, name: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _bad(name)
    out: dict[str, str] = {}
    for loc, value in raw.items():
        if loc not in LOCALES or not isinstance(value, str):
            raise _bad(name)
        value = value.strip()
        if len(value) > TEXT_MAX:
            raise _bad(name)
        if value:
            out[loc] = value
    return out


def _clean_sources(raw: Any, name: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > SOURCES_MAX:
        raise _bad(name)
    out: list[str] = []
    for url in raw:
        if not isinstance(url, str):
            raise _bad(name)
        url = _clean_url(url, name)
        if url not in out:
            out.append(url)
    return out


def _clean_url(raw: Any, name: str) -> str:
    if not isinstance(raw, str):
        raise _bad(name)
    url = raw.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or len(url) > URL_MAX:
        raise _bad(name)
    return url


def _clean_label(raw: Any, limit: int, name: str) -> str:
    """A stripped one-line label; empty when absent."""
    if raw is None:
        return ""
    if not isinstance(raw, str) or len(raw.strip()) > limit:
        raise _bad(name)
    return raw.strip()


def _clean_employer(raw: Any, name: str) -> dict[str, str]:
    if not isinstance(raw, dict) or not set(raw) <= {"name", "sector", "url"}:
        raise _bad(name)
    out = {"name": _clean_label(raw.get("name"), EMPLOYER_NAME_MAX, name)}
    if not out["name"]:
        raise _bad(name)
    sector = _clean_label(raw.get("sector"), EMPLOYER_SECTOR_MAX, name)
    if sector:
        out["sector"] = sector
    if raw.get("url") is not None:
        out["url"] = _clean_url(raw["url"], name)
    return out


def _clean_employers(raw: dict[str, Any], name: str) -> dict[str, Any]:
    """`{fields: {<opportunity field>: [{name, sector?, url?}]}}`."""
    if set(raw) != {"fields"} or not isinstance(raw["fields"], dict):
        raise _bad(name)
    fields: dict[str, list[dict[str, str]]] = {}
    for fkey, items in raw["fields"].items():
        where = f"{name}.fields.{fkey}"
        if fkey not in OPPORTUNITY_FIELDS or not isinstance(items, list):
            raise _bad(where)
        if len(items) > EMPLOYERS_MAX:
            raise _bad(where)
        cleaned = [_clean_employer(x, where) for x in items]
        if cleaned:
            fields[fkey] = cleaned
    return {"fields": fields} if fields else {}


def _is_amount(v: Any) -> bool:
    return (
        isinstance(v, int | float) and not isinstance(v, bool) and 0 < v <= SALARY_MAX
    )


def _clean_salaries(raw: dict[str, Any], name: str) -> dict[str, Any]:
    """`{currency: USD, year, overall_median_annual: number|null, by_field: {...}}`."""
    allowed = {"currency", "year", "overall_median_annual", "by_field"}
    if not set(raw) <= allowed or raw.get("currency") != "USD":
        raise _bad(f"{name}.currency" if set(raw) <= allowed else name)
    year = raw.get("year")
    if isinstance(year, bool) or not isinstance(year, int) or not 2000 <= year <= 2100:
        raise _bad(f"{name}.year")
    overall = raw.get("overall_median_annual")
    if overall is not None and not _is_amount(overall):
        raise _bad(f"{name}.overall_median_annual")
    by_raw = raw.get("by_field") or {}
    if not isinstance(by_raw, dict):
        raise _bad(f"{name}.by_field")
    by_field: dict[str, int | float] = {}
    for fkey, amount in by_raw.items():
        if fkey not in OPPORTUNITY_FIELDS or not _is_amount(amount):
            raise _bad(f"{name}.by_field.{fkey}")
        by_field[fkey] = amount
    if overall is None and not by_field:
        return {}
    return {
        "currency": "USD",
        "year": year,
        "overall_median_annual": overall,
        "by_field": by_field,
    }


_NESTED_VALUES: Final = {"employers": _clean_employers, "salaries": _clean_salaries}
"""Fact keys whose `values` have a fixed nested shape instead of flat values."""


def _is_score(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5


def _clean_value(value: Any, name: str) -> Any:
    """One normalized value; None means skip it."""
    if isinstance(value, str):
        value = value.strip()
        if len(value) > VALUE_STR_MAX:
            raise _bad(name)
        return value or None
    if value is not None and not isinstance(value, bool | int | float):
        raise _bad(name)
    return value


def _clean_values(key: str, raw: Any, name: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > VALUES_MAX:
        raise _bad(name)
    nested = _NESTED_VALUES.get(key)
    if nested is not None:
        return nested(raw, name) if raw else {}
    scored = _SCORED_VALUES.get(key, ())
    out: dict[str, Any] = {}
    for vname, value in raw.items():
        if not isinstance(vname, str) or not 0 < len(vname) <= 60:
            raise _bad(name)
        value = _clean_value(value, name)
        if value is None:
            continue
        if vname in scored and not _is_score(value):
            raise _bad(f"{name}.{vname}")
        out[vname] = value
    return out


def clean_fact(key: str, raw: Any) -> dict[str, Any] | None:
    """Return one normalized fact, or None when it holds nothing; raise when invalid."""
    name = f"facts.{key}"
    if key not in FACT_KEYS:
        raise _bad(name)
    if not isinstance(raw, dict):
        raise _bad(name)
    score = raw.get("score")
    if score is not None and not _is_score(score):
        raise _bad(f"{name}.score")
    values = _clean_values(key, raw.get("values"), f"{name}.values")
    text = _clean_text(raw.get("text"), f"{name}.text")
    sources = _clean_sources(raw.get("sources"), f"{name}.sources")
    if score is None and not values and not text:
        return None
    if (score is not None or values) and not sources:
        raise _bad(f"{name}.sources")
    return {"score": score, "values": values, "text": text, "sources": sources}


def clean_facts(raw: Any) -> dict[str, dict[str, Any]]:
    """Normalize a whole `facts` map, dropping empty facts; raise when invalid."""
    if not isinstance(raw, dict):
        raise _bad("facts")
    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        fact = clean_fact(key, value)
        if fact is not None:
            out[key] = fact
    return out


def clean_as_of(raw: Any) -> str:
    """A `YYYY-MM` month; raise when it is not."""
    if not isinstance(raw, str) or not _AS_OF.match(raw):
        raise _bad("as_of")
    return raw


def coverage(facts: dict[str, dict[str, Any]]) -> int:
    """Percent (0-100) of the fact keys that hold content."""
    filled = sum(1 for k in FACT_KEYS if k in facts)
    return round(100 * filled / len(FACT_KEYS))
