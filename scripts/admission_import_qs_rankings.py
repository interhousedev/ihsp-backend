"""Publish the QS World University Rankings overall rank of catalog institutions.

Reads QS's own public ranking table (the data file behind
https://www.topuniversities.com/world-university-rankings/2026), matches rows to
catalog institutions by exact normalised name or alias plus country, and stores
a `rankings` fact (system `qs`, subject `overall`) whose source is the
institution's QS page. Nothing is guessed: unmatched institutions get nothing.
Existing rankings of other systems or subjects are kept. Re-running replaces
only the QS overall entry.

    uv run python scripts/admission_import_qs_rankings.py --dry-run
    uv run python scripts/admission_import_qs_rankings.py --as-user <CURATOR UUID>
"""

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.modules.admission.infrastructure.catalog_proposals_repository import (  # noqa: E402
    SqlCatalogProposalRepository,
)
from app.modules.admission.infrastructure.orm.catalog import (  # noqa: E402
    FactRow,
    InstitutionRow,
)
from app.settings import load_settings  # noqa: E402
from app.shared.clock import SystemClock  # noqa: E402

SITE = "https://www.topuniversities.com"
DATA_URL = f"{SITE}/sites/default/files/qs-rankings-data/en/4061771.txt"
YEAR = 2026
# ISO 3166 alpha-2 (catalog) to the country names QS uses.
COUNTRIES = {
    "US": "United States",
    "UZ": "Uzbekistan",
    "CA": "Canada",
    "GB": "United Kingdom",
    "KZ": "Kazakhstan",
    "KR": "South Korea",
    "JP": "Japan",
    "IT": "Italy",
    "CN": "China (Mainland)",
    "ES": "Spain",
    "DE": "Germany",
    "BR": "Brazil",
    "FR": "France",
    "CH": "Switzerland",
    "HU": "Hungary",
    "HK": "Hong Kong SAR",
    "BE": "Belgium",
    "PL": "Poland",
    "SG": "Singapore",
    "CZ": "Czechia",
    "TR": "Türkiye",
    "BG": "Bulgaria",
    "FI": "Finland",
    "NO": "Norway",
    "MY": "Malaysia",
    "AE": "United Arab Emirates",
}
_TAG = re.compile(r"<[^>]+>")
_HREF = re.compile(r'href="(/universities/[a-z0-9-]+)"')
_PAREN = re.compile(r"\(([^)]*)\)")


def norm(text: str) -> str:
    """Casefolded, accent-free, punctuation-free name."""
    t = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def names_of(title: str) -> set[str]:
    """Normalised forms of a name: with and without its parenthesised part."""
    out = {norm(title), norm(_PAREN.sub(" ", title))}
    out.update(norm(m) for m in _PAREN.findall(title) if len(m.strip()) > 2)
    return {n for n in out if n}


def parse_rows(data: dict[str, Any]) -> list[dict[str, str]]:
    """`[{name, country, rank, url}]` of the ranked rows; N/A rows are dropped."""
    rows = []
    for r in data["data"]:
        rank = str(r.get("rank_display", "")).lstrip("=").strip()
        href = _HREF.search(r["title"])
        if not rank or rank.upper() == "N/A" or href is None:
            continue
        rows.append(
            {
                "name": _TAG.sub("", r["title"]).strip(),
                "country": r["country"],
                "rank": rank,
                "url": SITE + href.group(1),
            }
        )
    return rows


def rank_value(rank: str) -> int | str:
    """A whole number rank, or a band such as `1001-1200` / `1401+`."""
    return int(rank) if rank.isdigit() else rank


def match(
    rows: list[dict[str, str]], institutions: list[InstitutionRow]
) -> dict[Any, dict[str, str]]:
    """Institution id -> QS row, by exact normalised name/alias and country."""
    index: dict[tuple[str, str], list[dict[str, str]]] = {}
    for r in rows:
        for n in names_of(r["name"]):
            index.setdefault((n, r["country"]), []).append(r)
    found: dict[Any, dict[str, str]] = {}
    for inst in institutions:
        country = COUNTRIES.get(inst.country)
        if country is None:
            continue
        hits: dict[str, dict[str, str]] = {}
        for label in [inst.name, *(inst.aliases or [])]:
            for n in names_of(label):
                for r in index.get((n, country), []):
                    hits[r["url"]] = r
        if len(hits) == 1:
            found[inst.id] = next(iter(hits.values()))
    return found


async def _run(dry_run: bool, user: UUID | None) -> dict[str, Any]:
    from sqlalchemy import select

    from app.shared.db.engine import make_engine, make_sessionmaker

    if not dry_run and user is None:
        raise SystemExit("--as-user <UUID> is required unless --dry-run.")
    async with httpx.AsyncClient(
        headers={"User-Agent": "iht-admission-qs-import/1.0"}, timeout=60
    ) as http:
        response = await http.get(DATA_URL)
        response.raise_for_status()
    rows = parse_rows(response.json())
    settings = load_settings()
    engine = make_engine(settings.database.url, 2)
    report: dict[str, Any] = {"qs_rows": len(rows), "matched": [], "unmatched": []}
    try:
        async with make_sessionmaker(engine)() as session:
            q = select(InstitutionRow).where(InstitutionRow.status != "archived")
            institutions = list((await session.scalars(q)).all())
            found = match(rows, institutions)
            repo = SqlCatalogProposalRepository(session)
            now = SystemClock().now()
            for inst in sorted(institutions, key=lambda i: i.name):
                row = found.get(inst.id)
                if row is None:
                    report["unmatched"].append(inst.name)
                    continue
                kept = await _kept(session, inst.id)
                item = {
                    "system": "qs",
                    "subject": "overall",
                    "rank": rank_value(row["rank"]),
                    "year": YEAR,
                    "source_url": row["url"],
                }
                report["matched"].append(
                    {"name": inst.name, "rank": row["rank"], "qs_name": row["name"]}
                )
                if not dry_run and user is not None:
                    await repo.apply_facts(
                        inst.id,
                        {
                            "rankings": {
                                "value": [item, *kept],
                                "source_url": row["url"],
                                "year": YEAR,
                            }
                        },
                        user,
                        now,
                    )
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
    finally:
        await engine.dispose()
    return report


async def _kept(session: Any, institution_id: UUID) -> list[dict[str, Any]]:
    """Published ranking items other than QS overall, de-duplicated."""
    from sqlalchemy import select

    row = await session.scalar(
        select(FactRow).where(
            FactRow.entity_kind == "institution",
            FactRow.entity_id == institution_id,
            FactRow.key == "rankings",
            FactRow.status == "published",
        )
    )
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for x in row.value if row is not None and isinstance(row.value, list) else []:
        key = (x.get("system"), x.get("subject"))
        if key == ("qs", "overall") or key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out


def main() -> int:
    """Parse the flags, import and print a JSON report."""
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--as-user", type=UUID, default=None)
    a = p.parse_args()
    report = asyncio.run(_run(a.dry_run, a.as_user))
    json.dump(report, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
