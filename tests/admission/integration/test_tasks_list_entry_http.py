"""Tasks linked to a list entry, over real HTTP and PostgreSQL."""

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


async def test_task_links_to_own_list_entry_and_refuses_unknown(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
    engine: AsyncEngine,
) -> None:
    container, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.STUDENT, "taskentrystudent"
    )
    async with AsyncSession(engine) as s:
        await load_catalog(s, container.clock.now())
        await s.commit()
        inst = (await s.execute(select(InstitutionRow).limit(1))).scalars().one().id
    async with client:
        added = await client.post(
            "/v1/admission/list", json={"institution_id": str(inst)}
        )
        assert added.status_code == 201, added.text
        entry = added.json()["id"]
        made = await client.post(
            "/v1/admission/tasks", json={"title": "Essay", "list_entry_id": entry}
        )
        assert made.status_code == 200, made.text
        assert made.json()["list_entry_id"] == entry
        got = await client.get(f"/v1/admission/tasks/{made.json()['id']}")
        assert got.json()["list_entry_id"] == entry
        bad = await client.post(
            "/v1/admission/tasks",
            json={
                "title": "X",
                "list_entry_id": "00000000-0000-4000-8000-000000000001",
            },
        )
        assert bad.status_code == 422, bad.text
