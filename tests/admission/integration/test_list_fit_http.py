"""Fit per list entry over real HTTP and PostgreSQL."""

from app.modules.admission.infrastructure.catalog_loader import load_catalog
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.shared.actor import Role
from tests.admission.integration.test_intl_http import (  # noqa: F401
    _http,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

BASE = "/v1/admission"


async def test_list_fit_scores_each_entry_with_localised_lines(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
    engine: AsyncEngine,
) -> None:
    container, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "listfitstudent"
    )
    async with AsyncSession(engine) as s:
        await load_catalog(s, container.clock.now())
        await s.commit()
        inst = (await s.execute(select(InstitutionRow).limit(1))).scalars().one().id
    async with client:
        empty = await client.get(f"{BASE}/list/fit")
        assert empty.status_code == 200 and empty.json()["items"] == []
        added = await client.post(f"{BASE}/list", json={"institution_id": str(inst)})
        entry = added.json()["id"]
        body = (await client.get(f"{BASE}/list/fit")).json()
        assert body["weights"] == {
            "afford": 0.25,
            "goals": 0.3,
            "profile": 0.3,
            "traits": 0.15,
        }
        item = body["items"][0]
        assert item["list_entry_id"] == entry and item["institution_id"] == str(inst)
        assert [a["key"] for a in item["axes"]] == [
            "afford",
            "goals",
            "profile",
            "traits",
        ]
        for a in item["axes"]:
            assert a["score"] is None or 0 <= a["score"] <= 100
            assert a["why"] and "raise" in a
        ru = (
            await client.get(f"{BASE}/list/fit", headers={"Accept-Language": "ru"})
        ).json()["items"][0]
        assert ru["axes"][0]["why"] != item["axes"][0]["why"]
        await client.put(
            f"{BASE}/me/fit-preferences",
            json={
                "ratings": {
                    "price": 10,
                    "salary": 1,
                    "ai_resilience": 1,
                    "prestige": 1,
                    "academics": 1,
                    "social": 1,
                    "city": 1,
                    "home": 1,
                }
            },
        )
        after = (await client.get(f"{BASE}/list/fit")).json()
        assert after["weights"]["afford"] > 0.5
