"""The catalog load adds the seed supplemental prompts a fresh database lacks."""

import datetime as dt
import json

from app.modules.admission.infrastructure.catalog_loader import (
    _SUPP_PROMPTS,
    load_catalog,
    load_supp_prompts,
)
from app.modules.admission.infrastructure.orm.catalog import InstitutionRow
from app.modules.admission.infrastructure.orm.supp_prompts import SuppPromptRow
from app.shared.ids import new_id

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

NOW = dt.datetime(2026, 11, 23, tzinfo=dt.UTC)


def _seed_count(slug: str | None = None, cycle: str | None = None) -> int:
    seed = json.loads(_SUPP_PROMPTS.read_text("utf-8"))
    return sum(
        len(prompts)
        for s, entry in seed.items()
        if slug is None or s == slug
        for c, prompts in entry["cycles"].items()
        if cycle is None or c == cycle
    )


async def _count(s: AsyncSession) -> int:
    return int(await s.scalar(select(func.count()).select_from(SuppPromptRow)) or 0)


async def test_catalog_load_adds_seed_prompts_once(db_session: AsyncSession) -> None:
    await db_session.execute(delete(SuppPromptRow))
    await load_catalog(db_session, NOW)
    assert await _count(db_session) == _seed_count() == 85
    assert await load_supp_prompts(db_session) == 0
    assert await _count(db_session) == 85


async def test_curated_cycle_is_left_alone(db_session: AsyncSession) -> None:
    await load_catalog(db_session, NOW)
    await db_session.execute(delete(SuppPromptRow))
    harvard = await db_session.scalar(
        select(InstitutionRow.id).where(InstitutionRow.slug == "harvard")
    )
    assert harvard is not None
    db_session.add(
        SuppPromptRow(
            id=new_id(),
            institution_id=harvard,
            cycle="2025-26",
            position=0,
            prompt="Curator text",
            word_limit=100,
            required=True,
        )
    )
    await db_session.flush()

    added = await load_supp_prompts(db_session)

    assert added == 85 - _seed_count("harvard", "2025-26")
    rows = (
        await db_session.scalars(
            select(SuppPromptRow.prompt).where(
                SuppPromptRow.institution_id == harvard,
                SuppPromptRow.cycle == "2025-26",
            )
        )
    ).all()
    assert rows == ["Curator text"]
    assert await load_supp_prompts(db_session) == 0
