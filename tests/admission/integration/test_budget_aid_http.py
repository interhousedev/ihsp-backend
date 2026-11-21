"""Budget aid profile / admit rate and the list brief, over real HTTP and PostgreSQL."""

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


async def test_budget_shows_seeded_aid_profile_and_admit_rate_and_brief_runs(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
    engine: AsyncEngine,
) -> None:
    container, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "aidstudent"
    )
    async with AsyncSession(engine) as s:
        await load_catalog(s, container.clock.now())
        await s.commit()
        ids = {
            r.slug: r.id
            for r in (await s.execute(select(InstitutionRow))).scalars()
            if r.slug in ("columbia", "yale")
        }
    async with client:
        for slug in ("columbia", "yale"):
            added = await client.post(
                "/v1/admission/list", json={"institution_id": str(ids[slug])}
            )
            assert added.status_code == 201, added.text
        budget = await client.get("/v1/admission/chooser/budget")
        assert budget.status_code == 200, budget.text
        rows = {r["institution"]["id"]: r for r in budget.json()["rows"]}
        col = rows[str(ids["columbia"])]
        assert col["aid_profile"]["avg_aid_scope"] == "intl"
        assert col["aid_profile"]["avg_aid"] in (92699, "92699.00")
        assert col["aid_profile"]["meets_full_need"] is True
        assert col["admit_rate"]["scope"] == "intl"
        assert col["admit_rate"]["percent"] == 2.6
        yale = rows[str(ids["yale"])]
        assert yale["admit_rate"]["scope"] == "overall"
        brief = await client.post("/v1/admission/list/brief?locale=en")
        assert brief.status_code == 403, brief.text  # AI consent gate
        assert brief.json()["type"] == "admission/consent_required"
