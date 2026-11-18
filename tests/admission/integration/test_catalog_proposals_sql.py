"""Approved proposals write FactRows (and the cost and aid mirrors) on PostgreSQL."""

import asyncio
import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.catalog_proposals import (
    CatalogProposalService,
)
from app.modules.admission.domain.catalog_proposals import CatalogProposal
from app.modules.admission.domain.errors import (
    CatalogDuplicateError,
    CatalogFactInvalidError,
)
from app.modules.admission.infrastructure.catalog_proposals_repository import (
    SqlCatalogProposalRepository,
)
from app.modules.admission.infrastructure.orm.catalog import (
    AidPolicyRow,
    CatalogProposalRow,
    CostOfAttendanceRow,
    FactRow,
    InstitutionRow,
)
from app.shared.actor import Role
from app.shared.db.engine import make_sessionmaker
from app.shared.ids import new_id
from tests.admission.unit.test_access_policy import STAFF, World, _assign
from tests.fakes.clock import FixedClock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
REVIEWER = UUID("00000000-0000-0000-0000-00000000000a")
URL = "https://example.edu/admissions"


def _fact(value: object, year: int = 2025) -> dict[str, object]:
    return {"value": value, "source_url": URL, "year": year, "note": "Page 3"}


def _proposal(
    target: UUID | None, facts: dict[str, dict[str, object]]
) -> CatalogProposal:
    return CatalogProposal(
        id=new_id(),
        kind="institution",
        target_id=target,
        payload={"name": "Test University", "country": "GB"} if not target else {},
        source_url=URL,
        note=None,
        status="pending",
        proposed_by=REVIEWER,
        created_at=NOW,
        facts=facts,
    )


async def test_apply_writes_facts_and_mirrors_and_updates_in_place(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-INTL-12: apply writes reviewed facts and later ones update in place."""
    async with sessionmaker_in_tx() as s:
        repo = SqlCatalogProposalRepository(s)
        facts = {
            "acceptance_rate": _fact(12.5),
            "intl_coa_usd": _fact({"amount": 80000, "currency": "USD"}),
            "aid_basis": _fact("need_blind_full"),
        }
        inst = await repo.apply(_proposal(None, facts), reviewer_id=REVIEWER, now=NOW)
        rows = list(await s.scalars(select(FactRow).where(FactRow.entity_id == inst)))
        by_key = {r.key: r for r in rows}
        assert set(by_key) == set(facts)
        rate = by_key["acceptance_rate"]
        assert rate.reviewer_id == REVIEWER and rate.status == "published"
        assert (rate.unit, rate.cycle, rate.excerpt) == ("percent", 2025, "Page 3")
        coa = await s.scalar(
            select(CostOfAttendanceRow).where(
                CostOfAttendanceRow.institution_id == inst
            )
        )
        assert coa is not None and coa.total == 80000 and coa.currency == "USD"
        aid = await s.scalar(
            select(AidPolicyRow).where(AidPolicyRow.institution_id == inst)
        )
        assert aid is not None and aid.intl_need_based == "need_blind"
        assert aid.meets_full_need is True

        await repo.apply(
            _proposal(inst, {"acceptance_rate": _fact(9.0, 2026)}),
            reviewer_id=REVIEWER,
            now=NOW,
        )
        again = list(
            await s.scalars(
                select(FactRow).where(
                    FactRow.entity_id == inst, FactRow.key == "acceptance_rate"
                )
            )
        )
        assert [(r.id, r.status, r.cycle) for r in again] == [
            (rate.id, "published", 2026)
        ]


async def _pending(
    repo: SqlCatalogProposalRepository, payload: dict[str, object]
) -> UUID:
    p = dataclasses.replace(_proposal(None, {}), payload=payload)
    return (await repo.add(p)).id


async def _institution(s: AsyncSession, name: str, aliases: list[str]) -> UUID:
    row = InstitutionRow(id=new_id(), name=name, country="GB", aliases=aliases)
    s.add(row)
    await s.flush()
    return row.id


async def test_duplicate_pending_name_ignores_whitespace_runs(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-INTL-SEC-4: a pending name "Foo  Bar" matches the folded "foo bar"."""
    async with sessionmaker_in_tx() as s:
        repo = SqlCatalogProposalRepository(s)
        pid = await _pending(repo, {"name": "Foo  Bar", "country": "GB"})
        assert await repo.find_duplicate(["foo bar"], None) == ("proposal", pid)


async def test_duplicate_institution_name_ignores_padding_and_runs(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-INTL-SEC-4: an institution "  Foo  Bar " matches "foo bar"."""
    async with sessionmaker_in_tx() as s:
        iid = await _institution(s, "  Foo  Bar ", [])
        found = await SqlCatalogProposalRepository(s).find_duplicate(["foo bar"], None)
        assert found == ("institution", iid)


async def test_duplicate_institution_alias_ignores_whitespace_runs(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-INTL-SEC-4: an alias "Foo  Bar" matches the folded "foo bar"."""
    async with sessionmaker_in_tx() as s:
        iid = await _institution(s, "Unrelated Name", ["Foo  Bar"])
        found = await SqlCatalogProposalRepository(s).find_duplicate(["foo bar"], None)
        assert found == ("institution", iid)


async def test_duplicate_pending_alias_is_matched(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-INTL-SEC-4: the aliases of a pending create count as its names."""
    async with sessionmaker_in_tx() as s:
        repo = SqlCatalogProposalRepository(s)
        pid = await _pending(
            repo, {"name": "Other Name", "country": "GB", "aliases": ["Foo Bar"]}
        )
        assert await repo.find_duplicate(["foo bar"], None) == ("proposal", pid)


class _Access:
    def audit(self, event: object) -> None:
        pass


class _SqlUow:
    def __init__(self, s: AsyncSession) -> None:
        self.catalog_proposals = SqlCatalogProposalRepository(s)
        self.access = _Access()
        self._s = s

    async def __aenter__(self) -> "_SqlUow":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        await self._s.flush()


async def test_service_finds_sharp_s_duplicate_on_postgres(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-INTL-SEC-4: "Straße Universität" proposed again is a duplicate."""
    async with sessionmaker_in_tx() as s:
        known = await _institution(s, "Straße Universität", [])
        world = World()
        world.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
        ctx = await world.ctx(STAFF, Role.COUNSELOR)
        svc = CatalogProposalService(
            lambda: _SqlUow(s), FixedClock(NOW)  # type: ignore[arg-type,return-value]
        )
        with pytest.raises(CatalogDuplicateError) as e:
            await svc.propose(
                ctx,
                kind="institution",
                target_id=None,
                fields={"name": "Straße Universität", "country": "DE"},
                source_url=URL,
                note=None,
            )
        assert e.value.params == {"institution_id": str(known)}


async def _svc_ctx(
    s: AsyncSession,
) -> tuple[CatalogProposalService, AdmissionContext]:
    world = World()
    world.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    ctx = await world.ctx(STAFF, Role.COUNSELOR)
    svc = CatalogProposalService(
        lambda: _SqlUow(s), FixedClock(NOW)  # type: ignore[arg-type,return-value]
    )
    return svc, ctx


async def _submit(
    svc: CatalogProposalService,
    ctx: AdmissionContext,
    fields: dict[str, object],
    facts: dict[str, dict[str, object]] | None = None,
) -> CatalogProposal:
    return await svc.propose(
        ctx,
        kind="institution",
        target_id=None,
        fields=fields,
        source_url=URL,
        note=None,
        facts=facts,
    )


async def test_money_above_column_capacity_is_refused_at_submission(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-INTL-SEC-8: 10^10 is refused; the Numeric(12,2) maximum approves."""
    async with sessionmaker_in_tx() as s:
        svc, ctx = await _svc_ctx(s)
        too_big = {"intl_coa_usd": _fact({"amount": 10_000_000_000, "currency": "USD"})}
        with pytest.raises(CatalogFactInvalidError):
            await _submit(svc, ctx, {"name": "Big U", "country": "GB"}, too_big)
        top = {"intl_coa_usd": _fact({"amount": 9_999_999_999.99, "currency": "USD"})}
        saved = await _submit(svc, ctx, {"name": "Top U", "country": "GB"}, top)
        inst = await SqlCatalogProposalRepository(s).apply(
            saved, reviewer_id=REVIEWER, now=NOW
        )
        coa = await s.scalar(
            select(CostOfAttendanceRow).where(
                CostOfAttendanceRow.institution_id == inst
            )
        )
        assert coa is not None and coa.total == Decimal("9999999999.99")


async def test_pending_proposals_with_the_same_domain_are_duplicates(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """ADM-INTL-SEC-9: a second pending create with the same website is a duplicate."""
    async with sessionmaker_in_tx() as s:
        svc, ctx = await _svc_ctx(s)
        first = await _submit(
            svc,
            ctx,
            {"name": "Alpha U", "country": "GB", "website_domain": "Same.example.edu"},
        )
        with pytest.raises(CatalogDuplicateError) as e:
            await _submit(
                svc,
                ctx,
                {
                    "name": "Beta U",
                    "country": "GB",
                    "website_domain": "same.example.edu",
                },
            )
        assert e.value.params == {"proposal_id": str(first.id)}


class _GatedUow(_SqlUow):
    """Holds the commit until `release` is set, like a slow request."""

    def __init__(
        self, s: AsyncSession, reached: asyncio.Event, release: asyncio.Event
    ) -> None:
        super().__init__(s)
        self._reached, self._release = reached, release

    async def commit(self) -> None:
        self._reached.set()
        await self._release.wait()
        await self._s.commit()


class _Plain(_SqlUow):
    async def commit(self) -> None:
        await self._s.commit()


async def test_concurrent_same_name_submissions_serialise_on_postgres(
    engine: AsyncEngine,
) -> None:
    """ADM-INTL-SEC-10: B waits for A's commit, then sees the duplicate."""
    maker = make_sessionmaker(engine)
    reached, release = asyncio.Event(), asyncio.Event()
    name = f"Race University {new_id()}"
    fields = {"name": name, "country": "GB"}
    world = World()
    world.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    ctx = await world.ctx(STAFF, Role.COUNSELOR)
    try:
        async with maker() as sa, maker() as sb:
            gated = lambda: _GatedUow(sa, reached, release)  # noqa: E731
            plain = lambda: _Plain(sb)  # noqa: E731
            svc_a = CatalogProposalService(
                gated,  # type: ignore[arg-type]
                FixedClock(NOW),
            )
            svc_b = CatalogProposalService(
                plain,  # type: ignore[arg-type]
                FixedClock(NOW),
            )
            task_a = asyncio.create_task(_submit(svc_a, ctx, fields))
            await asyncio.wait_for(reached.wait(), 10)
            task_b = asyncio.create_task(_submit(svc_b, ctx, fields))
            done, _ = await asyncio.wait({task_b}, timeout=1)
            assert not done, "B must block on the submission lock"
            release.set()
            await task_a
            with pytest.raises(CatalogDuplicateError):
                await task_b
        async with maker() as s:
            rows = list(
                await s.scalars(
                    select(CatalogProposalRow).where(
                        CatalogProposalRow.payload["name"].astext == name
                    )
                )
            )
            assert len(rows) == 1
    finally:
        release.set()
        async with maker() as s:
            await s.execute(
                delete(CatalogProposalRow).where(
                    CatalogProposalRow.payload["name"].astext == name
                )
            )
            await s.commit()
