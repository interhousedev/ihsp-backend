"""Programs in the opportunities catalog: fields, filters, sort, pages, payload."""

from typing import Any

from app.modules.admission.application.opportunities import CatalogFilter
from app.modules.admission.domain.opportunities import OpportunityDraft
from app.shared.base_error import ValidationFailedError
from tests.admission.unit.test_access_policy import STAFF
from tests.admission.unit.test_opportunities import Env

import pytest

_ROWS: list[dict[str, Any]] = [
    {
        "title": "Research Science Institute",
        "country": "USA",
        "location": "Cambridge, MA",
        "tuition_usd": 0,
        "acceptance_rate": 3.0,
        "ranking": 1,
    },
    {
        "title": "Yale Young Global Scholars",
        "country": "USA",
        "location": "New Haven, CT",
        "tuition_usd": 6500,
        "acceptance_rate": 25.0,
        "ranking": 5,
    },
    {
        "title": "Lumiere Research Scholar",
        "country": "UK",
        "location": "Remote",
        "online": True,
        "tuition_usd": 3000,
        "acceptance_rate": None,
        "ranking": None,
    },
]


def _program(**kw: Any) -> OpportunityDraft:
    base: dict[str, Any] = {"kind": "program", "url": "https://example.org"}
    base.update(kw)
    return OpportunityDraft(**base)


async def _env() -> Env:
    e = Env()
    for row in _ROWS:
        await e.repo.apply(_program(**row), target_id=None, by=STAFF)
    return e


def test_payload_round_trip_keeps_catalog_fields() -> None:
    d = _program(**_ROWS[0], logo_url="https://example.org/l.png", duration_weeks=6)
    back = OpportunityDraft.from_payload(d.to_payload())
    assert back == d
    assert back.ranking == 1 and back.tuition_usd == 0 and back.online is False


def test_old_payload_without_catalog_fields_loads() -> None:
    d = OpportunityDraft.from_payload({"kind": "exam", "title": "SAT"})
    assert d.country is None and d.ranking is None and d.online is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("acceptance_rate", 101.0),
        ("acceptance_rate", -1.0),
        ("tuition_usd", -5),
        ("duration_weeks", 0),
        ("ranking", 0),
    ],
)
def test_catalog_field_problems(field: str, value: Any) -> None:
    assert field in _program(title="X", **{field: value}).problems()
    assert _program(title="X").problems() == []


async def test_non_https_logo_is_rejected() -> None:
    e = Env()
    a = await e.admin()
    with pytest.raises(ValidationFailedError):
        await e.svc.submit(a, _program(title="X", logo_url="http://x.org/l.png"))


async def test_filters() -> None:
    e = await _env()

    async def titles(**kw: Any) -> list[str]:
        page = await e.svc.catalog(CatalogFilter(kind="program", **kw))
        return [o.draft.title for o in page.items]

    assert len(await titles()) == 3
    assert await titles(country="usa") == [
        "Research Science Institute",
        "Yale Young Global Scholars",
    ]
    assert await titles(online=True) == ["Lumiere Research Scholar"]
    assert await titles(free=True) == ["Research Science Institute"]
    assert await titles(max_tuition=3000) == [
        "Lumiere Research Scholar",
        "Research Science Institute",
    ]
    assert await titles(query="new haven") == ["Yale Young Global Scholars"]


async def test_sort_puts_missing_values_last_and_pages() -> None:
    e = await _env()
    page = await e.svc.catalog(CatalogFilter(sort="ranking", page=1, size=2))
    assert page.total == 3 and page.size == 2
    assert [o.draft.ranking for o in page.items] == [1, 5]
    rest = await e.svc.catalog(CatalogFilter(sort="ranking", page=2, size=2))
    assert [o.draft.ranking for o in rest.items] == [None]
    cheap = await e.svc.catalog(CatalogFilter(sort="tuition"))
    assert [o.draft.tuition_usd for o in cheap.items] == [0, 3000, 6500]
    past = await e.svc.catalog(CatalogFilter(page=9, size=2))
    assert past.items == [] and past.total == 3
