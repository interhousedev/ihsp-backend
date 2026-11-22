"""Admission catalog import helper (prints JSON of catalog dicts; writes no DB).

uv run python scripts/admission_import_catalog.py seed
uv run python scripts/admission_import_catalog.py load   # upsert seed into the DB
uv run python scripts/admission_import_catalog.py scorecard "Stanford University" --year 2024
uv run python scripts/admission_import_catalog.py ipeds HD.csv ADM.csv IC.csv --year 2023

The Scorecard key is read from IHSP_ADMISSION__SCORECARD_API_KEY (optional).
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from app.modules.admission.infrastructure.catalog_data import load_seed
from app.modules.admission.infrastructure.importers import ipeds, scorecard


def _rows(path: str) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


async def _load() -> dict[str, int]:
    from app.modules.admission.infrastructure.catalog_loader import load_catalog
    from app.modules.admission.infrastructure.media_mirror import build_media_mirror
    from app.settings import load_settings
    from app.shared.db.engine import make_engine, make_sessionmaker

    settings = load_settings()
    engine = make_engine(settings.database.url, 2)
    try:
        async with make_sessionmaker(engine)() as session:
            report = await load_catalog(
                session, datetime.now(UTC), build_media_mirror(settings)
            )
            await session.commit()
        return {
            "institutions": report.institutions,
            "facts": report.facts,
            "scholarships": report.scholarships,
        }
    finally:
        await engine.dispose()


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    sub.add_parser("load")
    sc = sub.add_parser("scorecard")
    sc.add_argument("name")
    sc.add_argument("--year", type=int, required=True)
    ip = sub.add_parser("ipeds")
    ip.add_argument("hd")
    ip.add_argument("adm")
    ip.add_argument("ic")
    ip.add_argument("--year", type=int, required=True)
    a = p.parse_args()
    if a.cmd == "seed":
        out = load_seed()
    elif a.cmd == "load":
        out = asyncio.run(_load())
    elif a.cmd == "scorecard":
        qs = urllib.parse.urlencode(
            scorecard.search_params(
                a.name, os.environ.get("IHSP_ADMISSION__SCORECARD_API_KEY")
            )
        )
        with urllib.request.urlopen(f"{scorecard.API_URL}?{qs}", timeout=30) as r:
            out = scorecard.parse_api_payload(json.load(r), a.year)
    else:
        out = ipeds.parse_files(_rows(a.hd), _rows(a.adm), _rows(a.ic), a.year)
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
