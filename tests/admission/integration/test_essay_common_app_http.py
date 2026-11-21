"""Common App shared slot, categories, sealed short answers (HTTP + PostgreSQL)."""

from app.modules.admission.infrastructure.catalog_loader import load_catalog
from app.modules.admission.infrastructure.orm.catalog import FactRow, InstitutionRow
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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

BASE = "/v1/admission"
SHORT = "Name a book that changed how you think."
SECRET = "Dune taught me patience with deserts"


async def test_common_app_slot_categories_and_sealed_short_answer(
    make_container: ContainerFactory,
    overrides_cleaned: list[FastAPI],  # noqa: F811
    engine: AsyncEngine,
) -> None:
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "ca.admin"
    )
    async with AsyncSession(engine) as s:
        await load_catalog(s, container.clock.now())
        rows = (await s.execute(select(InstitutionRow).limit(2))).scalars().all()
        ca, own = rows[0].id, rows[1].id
        for inst, platforms in ((ca, ["common_app"]), (own, ["ucas"])):
            s.add(
                FactRow(
                    id=new_id(),
                    entity_kind="institution",
                    entity_id=inst,
                    key="application_platforms",
                    value=platforms,
                    confidence="manual",
                    status="published",
                )
            )
        for inst in (ca, own):
            s.add(
                SuppPromptRow(
                    id=new_id(),
                    institution_id=inst,
                    cycle="2026-27",
                    position=7,
                    prompt=SHORT,
                    word_limit=100,
                    required=True,
                    limit_unit="words",
                )
            )
        await s.commit()
    key = f"{ca}:7"
    async with client:
        student, essay_id = await _essay_student(
            container, client, switch, "ca.student", "I walked home."
        )
        for inst in (ca, own):
            added = await client.post(
                f"{BASE}/list", json={"institution_id": str(inst)}
            )
            assert added.status_code in (200, 201), added.text

        groups = (await client.get(f"{ESSAYS}/prompt-map")).json()["groups"]
        mine = next(g for g in groups if any(p["key"] == key for p in g["prompts"]))
        assert mine["category"] == "short_answer"
        ps_group = next(
            g for g in groups if any(p["institution_id"] is None for p in g["prompts"])
        )
        assert ps_group["category"] == "personal_statement"

        done = await client.put(
            f"{ESSAYS}/match/common-app", json={"essay_id": essay_id}
        )
        assert done.status_code == 200, done.text
        by_inst = {t["institution_id"]: t for t in done.json()["items"]}
        ps_ca, ps_own = by_inst[str(ca)]["slots"][0], by_inst[str(own)]["slots"][0]
        assert ps_ca["shared"] is True and ps_ca["essay_id"] == essay_id
        assert ps_own["shared"] is False and ps_own["essay_id"] is None
        emptied = await client.put(
            f"{ESSAYS}/match/common-app", json={"essay_id": None}
        )
        assert all(t["slots"][0]["essay_id"] is None for t in emptied.json()["items"])

        empty = await client.get(f"{ESSAYS}/short-answers/{key}")
        assert empty.json()["word_count"] == 0
        put = await client.put(f"{ESSAYS}/short-answers/{key}", json={"text": SECRET})
        assert put.status_code == 200, put.text
        assert put.json()["word_count"] == 6 and put.json()["text"] == SECRET
        too_long = await client.put(
            f"{ESSAYS}/short-answers/{key}", json={"text": "w " * 101}
        )
        assert too_long.status_code == 422
        unknown = await client.put(
            f"{ESSAYS}/short-answers/{new_id()}:0", json={"text": "x"}
        )
        assert unknown.status_code == 404

        match = (await client.get(f"{ESSAYS}/match/{ca}")).json()
        slot = next(sl for sl in match["slots"] if sl["prompt_key"] == key)
        assert slot["category"] == "short_answer"
        assert slot["short_answer"]["text"] == SECRET
        groups = (await client.get(f"{ESSAYS}/prompt-map")).json()["groups"]
        mine = next(g for g in groups if any(p["key"] == key for p in g["prompts"]))
        assert [a["text"] for a in mine["short_answers"]] == [SECRET]

    async with AsyncSession(engine) as s:
        raw = await s.scalar(
            text(
                "SELECT text FROM admission.essay_short_answers "
                "WHERE student_id = :s AND prompt_key = :k"
            ),
            {"s": student.user_id, "k": key},
        )
    assert isinstance(raw, bytes) and SECRET.encode() not in raw
