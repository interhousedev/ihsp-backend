"""Seed loader: deterministic ids make a second load rewrite the same rows."""

from typing import Any
from uuid import uuid4

from app.modules.admission.infrastructure.catalog_data import Institution, load_seed
from app.modules.admission.infrastructure.catalog_loader import load_catalog, seed_id
from app.modules.admission.infrastructure.orm.catalog import FactRow, InstitutionRow
from tests.admission.unit.fakes import NOW

import pytest
from pydantic import ValidationError


class _Session:
    def __init__(self) -> None:
        self.rows: dict[tuple[type, Any], Any] = {}

    async def merge(self, obj: Any) -> Any:
        self.rows[(type(obj), obj.id)] = obj
        return obj

    def add(self, obj: Any) -> None:
        # Country-facts rows are keyed by their country code, not an id.
        self.rows[(type(obj), getattr(obj, "id", None) or obj.country)] = obj

    async def get(self, model: type, key: Any) -> Any:
        return self.rows.get((model, key))

    async def flush(self) -> None:
        return None

    def _matches(self, stmt: Any) -> list[Any]:
        """Rows of the selected model whose columns hold every bound value."""
        model = stmt.column_descriptions[0]["entity"]
        values = set(stmt.compile().params.values())
        out = []
        for (t, _), o in self.rows.items():
            if t is not model:
                continue
            if model is InstitutionRow:
                hit = o.website_domain in values
            else:
                hit = {o.entity_id, o.key} <= values if model is FactRow else False
            if hit:
                out.append(o.id)
        return out

    async def scalar(self, stmt: Any) -> Any:
        found = self._matches(stmt)
        return found[0] if found else None

    async def scalars(self, stmt: Any) -> Any:
        return _Result(self._matches(stmt))


class _Result:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return self._items


async def test_load_is_idempotent_and_marks_verification() -> None:
    s = _Session()
    first = await load_catalog(s, NOW)  # type: ignore[arg-type]
    count = len(s.rows)
    second = await load_catalog(s, NOW)  # type: ignore[arg-type]
    assert first == second and len(s.rows) == count and first.institutions > 0
    insts = [o for (t, _), o in s.rows.items() if t is InstitutionRow]
    assert {i.status for i in insts} <= {"published", "provisional"}
    facts = [o for (t, _), o in s.rows.items() if t is FactRow]
    assert all(f.value is not None for f in facts)
    assert {f.confidence for f in facts} <= {"official", "manual"}


async def test_domain_match_enriches_existing_row_without_duplicates() -> None:
    seed = next(i for i in load_seed() if i["slug"] == "harvard")
    s = _Session()
    staff = InstitutionRow(
        id=uuid4(), slug="harvard-staff", name="Harvard", website_domain="harvard.edu"
    )
    own = FactRow(
        id=uuid4(),
        entity_kind="institution",
        entity_id=staff.id,
        key="acceptance_rate",
        value={"min": 99.0, "max": 99.0},
        confidence="manual",
    )
    s.rows[(InstitutionRow, staff.id)] = staff
    s.rows[(FactRow, own.id)] = own
    report = await load_catalog(s, NOW)  # type: ignore[arg-type]
    assert report.enriched >= 1
    insts = [o for (t, _), o in s.rows.items() if t is InstitutionRow]
    assert not [
        i for i in insts if i.website_domain == "harvard.edu" and i is not staff
    ]
    assert seed_id("institution", "harvard") not in {i.id for i in insts}
    assert staff.description == seed["description"]
    facts = [
        o for (t, _), o in s.rows.items() if t is FactRow and o.entity_id == staff.id
    ]
    assert [f for f in facts if f.key == "acceptance_rate"] == [own]
    assert own.value == {"min": 99.0, "max": 99.0}
    assert {"test_policy", "deadlines"} & {f.key for f in facts}
    count = len(s.rows)
    await load_catalog(s, NOW)  # type: ignore[arg-type]
    assert len(s.rows) == count


def test_seed_descriptions_and_domains() -> None:
    seed = load_seed()
    domains = [i["website_domain"] for i in seed if i["website_domain"]]
    assert len(domains) == len(set(domains))
    assert {"harvard.edu", "ox.ac.uk", "tum.de"} <= set(domains)
    for i in seed:
        d = i.get("description")
        assert d is None or all(0 < len(d[k]) <= 400 for k in ("en", "ru", "uz"))


def test_slug_defaults_from_domain_and_description_is_capped() -> None:
    base: dict[str, Any] = {
        "name": "X",
        "country": "US",
        "city": "Y",
        "source_url": "https://x.edu/a",
        "year": 2026,
    }
    assert Institution.model_validate(
        {**base, "website_domain": "www.Foo.edu"}
    ).slug == ("foo-edu")
    with pytest.raises(ValidationError):
        Institution.model_validate(base)
    with pytest.raises(ValidationError):
        Institution.model_validate(
            {
                **base,
                "slug": "x",
                "description": {"en": "a" * 401, "ru": "a", "uz": "a"},
            }
        )


async def test_seed_aliases_loaded_and_curator_aliases_kept() -> None:
    assert next(i for i in load_seed() if i["slug"] == "mit")["aliases"] == ["MIT"]
    s = _Session()
    await load_catalog(s, NOW)  # type: ignore[arg-type]
    mit = s.rows[(InstitutionRow, seed_id("institution", "mit"))]
    assert "MIT" in mit.aliases
    mit.aliases = ["Curator Alias", "mit"]
    await load_catalog(s, NOW)  # type: ignore[arg-type]
    assert mit.aliases == ["Curator Alias", "mit"]
