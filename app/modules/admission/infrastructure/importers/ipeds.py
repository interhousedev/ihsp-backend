"""IPEDS (NCES) survey files -> catalog institution dicts.

Joins HD (directory), ADM (admissions) and IC (charges) rows by UNITID.
Pure parsing over already-read CSV rows (dict per row).
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from app.modules.admission.infrastructure.importers.scorecard import (
    _num,
    city_type,
)

SOURCE_URL = "https://nces.ed.gov/ipeds/datacenter/DataFiles.aspx"

# ADMCON7 (SAT/ACT): 1 required, 2 recommended, 3 neither, 5 considered if submitted.
_TEST = {1: "required", 2: "optional", 3: "optional", 5: "optional"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_institution(
    hd: Mapping[str, Any],
    adm: Mapping[str, Any] | None,
    ic: Mapping[str, Any] | None,
    year: int,
) -> dict[str, Any]:
    """Map one IPEDS institution (HD, ADM and IC rows) to a catalog dict."""
    src = SOURCE_URL
    adm = adm or {}
    ic = ic or {}
    applied, admitted = _num(adm.get("APPLCN")), _num(adm.get("ADMSSN"))
    rate = round(admitted / applied * 100, 1) if applied and admitted else None
    test = _num(adm.get("ADMCON7"))
    tuition = _num(ic.get("TUITION3"))  # out-of-state tuition
    name = str(hd["INSTNM"])
    web = str(hd.get("WEBADDR") or "")
    if web and not web.startswith("http"):
        web = f"https://{web}"
    return {
        "slug": _slug(name),
        "name": name,
        "country": "US",
        "city": (
            f"{hd.get('CITY')}, {hd.get('STABBR')}"
            if hd.get("STABBR")
            else str(hd.get("CITY") or "")
        ),
        "city_type": city_type(hd.get("LOCALE")),
        "fields": [],
        "acceptance_rate": (
            None
            if rate is None
            else {"min": rate, "max": rate, "source_url": src, "year": year}
        ),
        "test_policy": (
            None
            if test is None or int(test) not in _TEST
            else {"value": _TEST[int(test)], "source_url": src, "year": year}
        ),
        "intl_tuition_usd": (
            None
            if tuition is None
            else {"value": int(tuition), "source_url": src, "year": year}
        ),
        "source_url": web or src,
        "year": year,
        "verified": False,
    }


def parse_files(
    hd_rows: Iterable[Mapping[str, Any]],
    adm_rows: Iterable[Mapping[str, Any]],
    ic_rows: Iterable[Mapping[str, Any]],
    year: int,
) -> list[dict[str, Any]]:
    """Join the three IPEDS files by UNITID into catalog dicts."""
    adm = {r["UNITID"]: r for r in adm_rows}
    ic = {r["UNITID"]: r for r in ic_rows}
    return [
        parse_institution(h, adm.get(h["UNITID"]), ic.get(h["UNITID"]), year)
        for h in hd_rows
    ]
