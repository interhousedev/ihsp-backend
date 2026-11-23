"""Catalog push service: per-item statuses, curator rule, batch size, limit, audit."""

from types import SimpleNamespace
from typing import Any

from app.modules.admission.application.catalog_push import CatalogPushService
from app.modules.admission.domain.catalog_push import COUNTRY_BATCH_MAX, PushResult
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    CatalogPushLimitError,
)
from app.modules.admission.infrastructure.country_facts_loader import (
    load_country_seed,
)
from app.shared.base_error import RateLimitedError, ValidationFailedError
from app.shared.ids import new_id
from tests.admission.unit.test_country_facts import _Repo

import pytest

USER = new_id()


class _Uow:
    def __init__(self, events: list[Any]) -> None:
        self.access = SimpleNamespace(audit=events.append)

    async def __aenter__(self) -> "_Uow":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _Writer:
    async def upsert(self, items: list[dict[str, Any]]) -> list[PushResult]:
        return [
            PushResult(i, str(d.get("slug")), "created") for i, d in enumerate(items)
        ]


class _Limiter:
    def __init__(self, limit: int) -> None:
        self.left = limit

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        self.left -= 1
        if self.left < 0:
            raise RateLimitedError(params={"retry_after": 60})
        return 1


def _ctx() -> Any:
    return SimpleNamespace(user_id=USER, actor=SimpleNamespace(user_id=USER))


def _service(
    repo: _Repo, events: list[Any], *, curator: bool = True, limit: int = 100
) -> CatalogPushService:
    return CatalogPushService(
        lambda: _Uow(events),  # type: ignore[arg-type,return-value]
        repo,
        _Writer(),
        lambda _ctx: curator,
        _Limiter(limit),  # type: ignore[arg-type]
    )


def _item() -> dict[str, Any]:
    first = load_country_seed()[0]
    return {k: first[k] for k in ("country", "as_of", "facts")}


async def test_countries_created_then_unchanged_then_updated() -> None:
    repo, events = _Repo(), list[Any]()
    service = _service(repo, events)
    item = _item()

    first = await service.push_countries(_ctx(), [item])
    again = await service.push_countries(_ctx(), [item])
    newer = await service.push_countries(_ctx(), [{**item, "as_of": "2030-01"}])

    assert [r.status for r in first + again + newer] == [
        "created",
        "unchanged",
        "updated",
    ]
    assert repo.rows[item["country"]].status == "draft"
    assert events[0].action == "catalog.pushed"
    assert events[0].meta["counts"] == {"created": 1}


async def test_verified_country_is_skipped_unless_overwritten() -> None:
    repo, events = _Repo(), list[Any]()
    service = _service(repo, events)
    item = _item()
    await service.push_countries(_ctx(), [item])
    await repo.set_verified(item["country"], USER)
    changed = {**item, "as_of": "2030-01"}

    skipped = await service.push_countries(_ctx(), [changed])
    forced = await service.push_countries(_ctx(), [changed], overwrite_verified=True)

    assert skipped[0].status == "skipped"
    assert forced[0].status == "updated"


async def test_bad_items_are_invalid_and_do_not_stop_the_batch() -> None:
    repo, events = _Repo(), list[Any]()
    item = _item()
    results = await _service(repo, events).push_countries(
        _ctx(), [{**item, "country": "ZZZ"}, {**item, "as_of": "soon"}, item]
    )

    assert [(r.status, r.field) for r in results] == [
        ("invalid", "country"),
        ("invalid", "as_of"),
        ("created", None),
    ]


async def test_non_curator_is_refused() -> None:
    with pytest.raises(AdmissionForbiddenError):
        await _service(_Repo(), [], curator=False).push_countries(_ctx(), [_item()])


async def test_batch_size_is_bounded() -> None:
    service = _service(_Repo(), [])
    with pytest.raises(ValidationFailedError):
        await service.push_countries(_ctx(), [])
    with pytest.raises(ValidationFailedError):
        await service.push_countries(_ctx(), [_item()] * (COUNTRY_BATCH_MAX + 1))


async def test_limit_raises_catalog_push_limit() -> None:
    service = _service(_Repo(), [], limit=1)
    await service.push_institutions(_ctx(), [{"slug": "a"}])
    with pytest.raises(CatalogPushLimitError):
        await service.push_institutions(_ctx(), [{"slug": "b"}])
