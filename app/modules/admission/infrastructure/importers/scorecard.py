"""College Scorecard (US Dept. of Education) -> catalog institution dicts.

Pure parsing; fetching is separate. The API key is optional
(`IHSP_ADMISSION__SCORECARD_API_KEY`); without it `DEMO_KEY` rate limits apply.
Bulk CSV rows use the dotted field names as column headers, same as the API.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

API_URL = "https://api.data.gov/ed/collegescorecard/v1/schools"
SOURCE_URL = "https://collegescorecard.ed.gov/data/"
FIELDS = (
    "id,school.name,school.city,school.state,school.locale,school.school_url,"
    "latest.admissions.admission_rate.overall,"
    "latest.admissions.test_requirements,"
    "latest.cost.tuition.out_of_state,latest.cost.attendance.academic_year"
)

# Scorecard `school.test_requirements` codes (admissions.test_requirements).
_TEST = {1: "required", 2: "optional", 3: "optional", 5: "optional", 4: "blind"}


def city_type(locale: Any) -> str | None:
    """NCES locale code: 11-13 city, 21-23 suburb, 31-43 town/rural."""
    try:
        code = int(locale)
    except (TypeError, ValueError):
        return None
    if 11 <= code <= 13:
        return "urban"
    if 21 <= code <= 23:
        return "suburban"
    if 31 <= code <= 43:
        return "rural"
    return None


def _num(v: Any) -> float | None:
    if v in (None, "", "NULL", "PrivacySuppressed"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_school(row: Mapping[str, Any], year: int) -> dict[str, Any]:
    """One Scorecard record (flat dotted keys) to the catalog shape."""
    src = SOURCE_URL
    rate = _num(row.get("latest.admissions.admission_rate.overall"))
    tuition = _num(row.get("latest.cost.tuition.out_of_state"))
    coa = _num(row.get("latest.cost.attendance.academic_year"))
    test = _num(row.get("latest.admissions.test_requirements"))
    name = str(row["school.name"])
    city = str(row.get("school.city") or "")
    state = row.get("school.state")
    web = str(row.get("school.school_url") or "")
    if web and not web.startswith("http"):
        web = f"https://{web}"
    return {
        "slug": _slug(name),
        "name": name,
        "country": "US",
        "city": f"{city}, {state}" if city and state else city,
        "city_type": city_type(row.get("school.locale")),
        "fields": [],
        "acceptance_rate": (
            None
            if rate is None
            else {
                "min": round(rate * 100, 1),
                "max": round(rate * 100, 1),
                "source_url": src,
                "year": year,
            }
        ),
        "test_policy": (
            None
            if test is None
            else {"value": _TEST.get(int(test)), "source_url": src, "year": year}
        ),
        "intl_tuition_usd": (
            None
            if tuition is None
            else {"value": int(tuition), "source_url": src, "year": year}
        ),
        "intl_coa_usd": (
            None
            if coa is None
            else {"value": int(coa), "source_url": src, "year": year}
        ),
        "source_url": web or src,
        "year": year,
        "verified": False,
    }


def parse_api_payload(payload: Mapping[str, Any], year: int) -> list[dict[str, Any]]:
    """`results` of an API response (flat keys via `fields=`) to catalog dicts."""
    return [parse_school(r, year) for r in payload.get("results", [])]


def parse_rows(rows: Iterable[Mapping[str, Any]], year: int) -> list[dict[str, Any]]:
    """Named Scorecard rows (flat keys) to catalog dicts."""
    return [parse_school(r, year) for r in rows if r.get("school.name")]


def search_params(name: str, api_key: str | None) -> dict[str, str]:
    """Query parameters of a College Scorecard name search."""
    return {
        "api_key": api_key or "DEMO_KEY",
        "school.name": name,
        "fields": FIELDS,
        "per_page": "5",
    }
