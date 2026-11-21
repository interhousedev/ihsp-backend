"""Prompt map (list scope), essays summary and match list over HTTP and PostgreSQL."""

from app.modules.admission.infrastructure.catalog_loader import load_catalog
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.modules.admission.infrastructure.orm.supp_prompts import SuppPromptRow
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.admission.integration.test_intl_http import (  # noqa: F401
    ESSAYS,
    _essay_student,
    _http,
    clean_admission,
    overrides_cleaned,
)
from tests.integration.conftest import ContainerFactory

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

BASE = "/v1/admission"
PROMPT = "Describe a place where you feel most yourself and why it matters."


async def test_ledger_prompt_map_essays_and_match(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
    engine: AsyncEngine,
) -> None:
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "ledger.admin"
    )
    async with AsyncSession(engine) as s:
        await load_catalog(s, container.clock.now())
        rows = (await s.execute(select(InstitutionRow).limit(2))).scalars().all()
        listed, other = rows[0].id, rows[1].id
        for inst in (listed, other):
            s.add(
                SuppPromptRow(
                    id=new_id(),
                    institution_id=inst,
                    cycle="2026-27",
                    position=0,
                    prompt=PROMPT,
                    word_limit=100,
                    required=True,
                    limit_unit="words",
                )
            )
        await s.commit()
    async with client:
        _, essay_id = await _essay_student(
            container, client, switch, "ledger.student", "I walked home."
        )
        added = await client.post(f"{BASE}/list", json={"institution_id": str(listed)})
        assert added.status_code in (200, 201), added.text

        scoped = await client.get(f"{ESSAYS}/prompt-map", params={"scope": "list"})
        assert scoped.status_code == 200, scoped.text
        groups = scoped.json()["groups"]
        mine = [g for g in groups if any(p["in_list"] for p in g["prompts"])]
        assert mine and all(
            any(p["in_list"] or p["institution_id"] is None for p in g["prompts"])
            for g in groups
        )
        g = mine[0]
        assert g["label"] and g["in_list_count"] == 1
        assert g["essay_ids"] == [] and g["due_utc"] is None
        assert g["due_predicted"] is False

        every = await client.get(f"{ESSAYS}/prompt-map", params={"scope": "all"})
        assert len(every.json()["groups"]) >= len(groups)

        rows = (await client.get(ESSAYS)).json()
        item = next(r for r in (rows["items"] if "items" in rows else rows))
        assert item["id"] == essay_id and item["targets"] == []
        assert item["forked_from"] is None and item["uniqueness"] is None
        assert item["deep_read"] == "none" and item["deep_read_at"] is None

        match = await client.get(f"{ESSAYS}/match")
        assert match.status_code == 200, match.text
        (table,) = match.json()["items"]
        assert table["institution_id"] == str(listed)
        slot = next(sl for sl in table["slots"] if sl["slot"] == "supp:0")
        assert slot["required"] is True and slot["assigned"] is None
        assert slot["word_limit"] == 100
