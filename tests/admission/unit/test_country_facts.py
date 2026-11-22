"""Country facts: validation, coverage, the curator rules and the seed file."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.country_facts import CountryFactsService
from app.modules.admission.domain.country_facts import (
    FACT_KEYS,
    CountryFacts,
    clean_fact,
    clean_facts,
    coverage,
    opportunity_fields_of,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.infrastructure.country_facts_loader import (
    load_country_seed,
)
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id

import pytest

SRC = "https://example.org/source"
EDITOR = new_id()


class _Repo:
    def __init__(self) -> None:
        self.rows: dict[str, CountryFacts] = {}

    async def get_many(self, codes: list[str]) -> list[CountryFacts]:
        return [self.rows[c] for c in codes if c in self.rows]

    async def list_all(self) -> list[CountryFacts]:
        return list(self.rows.values())

    async def save(
        self,
        country: str,
        *,
        as_of: str,
        facts: dict[str, dict[str, Any]],
        editor: UUID,
        verified: bool,
    ) -> CountryFacts:
        row = CountryFacts(
            country, as_of, facts, "verified" if verified else "draft", editor
        )
        self.rows[country] = row
        return row

    async def set_verified(self, country: str, editor: UUID) -> CountryFacts | None:
        old = self.rows.get(country)
        if old is None:
            return None
        return await self.save(
            country, as_of=old.as_of, facts=old.facts, editor=editor, verified=True
        )


def _ctx() -> Any:
    return SimpleNamespace(actor=SimpleNamespace(user_id=EDITOR))


def _service(curator: bool = True) -> tuple[CountryFactsService, _Repo]:
    repo = _Repo()
    return CountryFactsService(repo, lambda _ctx: curator), repo


def _fact(**over: Any) -> dict[str, Any]:
    return {"score": 4, "values": {}, "text": {"en": "ok"}, "sources": [SRC]} | over


def test_fact_needs_a_source_when_it_has_numbers() -> None:
    with pytest.raises(ValidationFailedError):
        clean_fact("safety", _fact(sources=[]))
    assert clean_fact("safety", _fact(score=None, values={}, sources=[])) is not None
    assert clean_fact("safety", {"score": None, "values": {}, "text": {}}) is None


def test_scores_urls_and_keys_are_checked() -> None:
    for bad in (_fact(score=6), _fact(sources=["http://insecure.example"])):
        with pytest.raises(ValidationFailedError):
            clean_fact("safety", bad)
    with pytest.raises(ValidationFailedError):
        clean_fact("unknown_key", _fact())
    with pytest.raises(ValidationFailedError):
        clean_fact("opportunities", _fact(values={"cs_it": 9}))
    with pytest.raises(ValidationFailedError):
        clean_fact("safety", _fact(text={"de": "x"}))


def test_coverage_counts_filled_keys() -> None:
    facts = clean_facts({"safety": _fact(), "climate": _fact()})
    assert coverage(facts) == round(100 * 2 / len(FACT_KEYS))


def test_student_fields_map_to_opportunity_keys() -> None:
    names = ["Computer Science", "Computer science"]
    assert opportunity_fields_of(names) == ["cs_it"]
    assert opportunity_fields_of(["no such field xyz"]) == []


def test_seed_file_is_valid_and_every_number_has_a_source() -> None:
    seed = {e["country"]: e for e in load_country_seed()}
    assert {"US", "GB", "DE"} <= set(seed)
    for entry in seed.values():
        for fact in entry["facts"].values():
            assert fact["sources"]


async def test_curator_saves_lists_and_verifies() -> None:
    service, _ = _service()
    saved = await service.save(
        _ctx(), "us", as_of="2026-11", facts={"safety": _fact()}, verified=False
    )
    assert saved.status == "draft"
    lines = await service.summaries(_ctx(), query=None, status=None)
    us = next(s for s in lines if s.country == "US")
    assert us.status == "draft" and us.coverage > 0
    assert next(s for s in lines if s.country == "FR").status == "missing"
    only = await service.summaries(_ctx(), query=None, status="draft")
    assert [s.country for s in only] == ["US"]
    assert (await service.verify(_ctx(), "US")).status == "verified"
    with pytest.raises(AdmissionNotFoundError):
        await service.verify(_ctx(), "FR")


async def test_non_curator_cannot_edit_but_anyone_reads() -> None:
    service, repo = _service(curator=False)
    repo.rows["US"] = CountryFacts("US", "2026-11", {}, "draft")
    with pytest.raises(AdmissionForbiddenError):
        await service.save(_ctx(), "US", as_of="2026-11", facts={}, verified=False)
    assert [r.country for r in await service.read(["us", "US"])] == ["US"]
    with pytest.raises(AdmissionNotFoundError):
        await service.read(["ZZ"])
