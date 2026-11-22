"""Idempotent load of the seed country facts.

The seed is `catalog_data/countries/country_facts.json`.

A row a staff member saved (`verified_by` set) is never overwritten by the seed;
every other row is replaced by the seed entry of the same country.
"""

import json
from pathlib import Path
from typing import Any

from app.modules.admission.domain.country_facts import (
    clean_as_of,
    clean_facts,
    is_country,
)
from app.modules.admission.infrastructure.orm.country_facts import CountryFactsRow
from app.shared.base_error import ValidationFailedError

from sqlalchemy.ext.asyncio import AsyncSession

SEED_FILE = Path(__file__).parent / "catalog_data" / "countries" / "country_facts.json"


def load_country_seed() -> list[dict[str, Any]]:
    """The validated seed entries `{country, as_of, facts}`; raise on a bad entry."""
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for entry in data.get("countries", []):
        code = str(entry.get("country", "")).upper()
        if not is_country(code):
            raise ValidationFailedError(params={"field": "country"})
        out.append(
            {
                "country": code,
                "as_of": clean_as_of(entry.get("as_of")),
                "facts": clean_facts(entry.get("facts") or {}),
            }
        )
    return out


async def load_country_facts(session: AsyncSession) -> int:
    """Upsert the seed countries; return how many rows were written. Caller commits."""
    written = 0
    for entry in load_country_seed():
        row = await session.get(CountryFactsRow, entry["country"])
        if row is not None and row.verified_by is not None:
            continue
        if row is None:
            row = CountryFactsRow(country=entry["country"], status="draft")
            session.add(row)
        row.as_of = entry["as_of"]
        row.facts = entry["facts"]
        written += 1
    await session.flush()
    return written
