"""The survey country list leads with every catalog country."""

from app.modules.admission.application.config import merge_countries
from app.modules.admission.domain.countries import COUNTRIES
from tests.admission.unit.fakes import FakeUow
from tests.admission.unit.test_access_policy import World


def test_catalog_countries_come_first_and_nothing_is_dropped() -> None:
    out = merge_countries(["us", "KZ", "GB", "US"])
    assert out[:3] == ("GB", "KZ", "US")
    assert set(out) == set(COUNTRIES) | {"GB", "KZ", "US"}
    assert len(out) == len(set(out))


async def test_repository_query_returns_distinct_upper_codes() -> None:
    w = World()
    async with FakeUow(w.store) as uow:
        assert await uow.catalog.countries() == []
