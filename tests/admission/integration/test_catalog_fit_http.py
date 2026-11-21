"""Fit on catalog and match payloads, `sort=fit`, and `estimates_visible`."""

from app.modules.admission.infrastructure.catalog_loader import load_catalog
from app.shared.actor import Role
from tests.admission.integration.test_intl_http import (  # noqa: F401
    _http,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

BASE = "/v1/admission"


async def test_catalog_fit_sort_matches_and_me(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
    engine: AsyncEngine,
) -> None:
    container, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "catfitstudent"
    )
    async with AsyncSession(engine) as s:
        await load_catalog(s, container.clock.now())
        await s.commit()
    async with client:
        me = await client.get(f"{BASE}/me")
        assert me.status_code == 200 and isinstance(
            me.json()["estimates_visible"], bool
        )
        page = (
            await client.get(f"{BASE}/catalog/institutions", params={"limit": 50})
        ).json()
        assert page["items"], page
        scored = [i for i in page["items"] if i["fit_total"] is not None]
        assert scored, "non-list institutions get a fit"
        assert all(0 <= i["fit_total"] <= 100 for i in scored)
        assert all(0 <= i["known_share"] <= 1 for i in scored)
        ordered = (
            await client.get(
                f"{BASE}/catalog/institutions", params={"limit": 50, "sort": "fit"}
            )
        ).json()["items"]
        totals = [i["fit_total"] for i in ordered]
        seen_null = False
        for t in totals:
            if t is None:
                seen_null = True
            else:
                assert not seen_null, "nulls last"
        known = [t for t in totals if t is not None]
        assert known == sorted(known, reverse=True)
        one = await client.get(f"{BASE}/catalog/institutions/{ordered[0]['id']}")
        assert one.status_code == 200 and "fit_total" in one.json()
        feed = await client.get(f"{BASE}/matches")
        assert feed.status_code == 200, feed.text
        for m in feed.json()["items"]:
            for key in (
                "fit_total",
                "known_share",
                "avg_aid_intl",
                "intl_acceptance_rate",
                "meets_full_need",
                "next_deadline",
            ):
                assert key in m
