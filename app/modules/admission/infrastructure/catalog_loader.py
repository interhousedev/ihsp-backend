"""Idempotent load of the seed catalog into the admission tables (§3.4, §11.1).

Every row has a deterministic UUIDv5 id derived from the seed key (slug, url, fact
key), so a second run updates the same rows instead of adding new ones. Reviewed
seed entries (`verified`) are published with `official` facts; the rest stay
`provisional` with `manual` facts and are shown as unverified.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.modules.admission.infrastructure.catalog_data import load_programs, load_seed
from app.modules.admission.infrastructure.org_media import (
    OrgMedia,
    by_domain,
    load_org_media,
    normalize_domain,
)
from app.modules.admission.infrastructure.orm.catalog import (
    AidPolicyRow,
    CostOfAttendanceRow,
    FactRow,
    InstitutionRow,
    ScholarshipRow,
    SourceRow,
)

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_NS = uuid5(NAMESPACE_URL, "admission.catalog.seed")
_AID = {
    "need_blind_full": ("need_blind", True),
    "need_aware": ("need_aware", None),
    "merit_only": ("none", None),
    "none": ("none", None),
}
"""Seed aid basis → (`intl_need_based`, `meets_full_need`)."""


def seed_id(*parts: object) -> UUID:
    """The deterministic id of a seed row."""
    return uuid5(_NS, ":".join(str(p) for p in parts))


@dataclass(frozen=True, slots=True)
class LoadReport:
    """Rows written by one load (inserted or refreshed)."""

    institutions: int
    facts: int
    scholarships: int
    skipped: int


class _Loader:
    def __init__(
        self, session: AsyncSession, now: dt.datetime, media: dict[str, OrgMedia]
    ) -> None:
        self.s = session
        self.now = now
        self.media = media
        self.facts = 0
        self.sources: set[UUID] = set()

    async def source(self, url: object) -> UUID | None:
        if not url:
            return None
        sid = seed_id("source", url)
        if sid not in self.sources:
            await self.s.merge(
                SourceRow(id=sid, kind="official_page", url=str(url)[:2000])
            )
            self.sources.add(sid)
        return sid

    async def fact(
        self,
        inst: UUID,
        key: str,
        value: Any,
        *,
        url: object,
        year: int | None,
        note: str | None,
        verified: bool,
        unit: str | None = None,
    ) -> None:
        if value is None:
            return
        fid = seed_id("fact", inst, key)
        existing = await self.s.get(FactRow, fid)
        if existing is not None and existing.reviewer_id is not None:
            return  # a staff-reviewed fact is never overwritten by the seed
        await self.s.merge(
            FactRow(
                id=fid,
                entity_kind="institution",
                entity_id=inst,
                key=key,
                value=value,
                unit=unit,
                cycle=year,
                source_id=await self.source(url),
                excerpt=(note or None) and note[:300],
                checked_at=self.now,
                confidence="official" if verified else "manual",
                status="published",
            )
        )
        self.facts += 1

    async def institution(self, d: dict[str, Any]) -> int:
        inst = seed_id("institution", d["slug"])
        verified = bool(d["verified"])
        org = self.media.get(normalize_domain(d.get("website_domain")) or "")
        await self.s.merge(
            InstitutionRow(
                id=inst,
                slug=d["slug"],
                name=d["name"],
                country=d["country"],
                city=d["city"],
                website_domain=normalize_domain(d.get("website_domain")),
                kind="university",
                status="published" if verified else "provisional",
                logo_url=d.get("logo_url") or (org.logo_url if org else None),
                cover_url=d.get("cover_url") or (org.cover_url if org else None),
            )
        )
        base = {"url": d["source_url"], "year": d["year"], "verified": verified}

        async def put(
            key: str, f: dict[str, Any] | None, unit: str | None = None
        ) -> None:
            if not f:
                return
            await self.fact(
                inst,
                key,
                f.get("value"),
                url=f.get("source_url") or base["url"],
                year=f.get("year") or base["year"],
                note=f.get("note"),
                verified=verified,
                unit=unit,
            )

        await self.fact(inst, "city_type", d.get("city_type"), note=None, **base)
        await self.fact(
            inst, "institution_type", d.get("institution_type"), note=None, **base
        )
        await self.fact(inst, "fields", d.get("fields") or None, note=None, **base)
        rate = d.get("acceptance_rate")
        if rate and (rate.get("min") is not None or rate.get("max") is not None):
            await self.fact(
                inst,
                "acceptance_rate",
                {"min": rate.get("min"), "max": rate.get("max")},
                url=rate.get("source_url") or base["url"],
                year=rate.get("year") or base["year"],
                note=rate.get("note"),
                verified=verified,
                unit="percent",
            )
        await put("intl_acceptance_rate", d.get("intl_acceptance_rate"), unit="percent")
        await put("test_policy", d.get("test_policy"))
        for key in ("intl_tuition_usd", "intl_coa_usd"):
            f = d.get(key)
            await put(key, f, (f or {}).get("currency", "USD"))
        aid = d.get("aid") or {}
        await put("aid_basis", aid.get("basis"))
        await put("merit_for_internationals", aid.get("merit_for_internationals"))
        await put("meets_full_need", aid.get("meets_full_need"))
        await put("crime_index", (d.get("safety") or {}).get("crime_index"))
        deadlines = [
            {
                "plan": x["plan"],
                "date": str(x["date"]) if x.get("date") else None,
                "cycle": x["cycle"],
                "note": x.get("note"),
                "source_url": str(x["source_url"]) if x.get("source_url") else None,
            }
            for x in d.get("deadlines") or []
        ]
        await self.fact(inst, "deadlines", deadlines or None, note=None, **base)
        await self.cost_and_aid(inst, d, verified)
        n = 0
        for sch in d.get("scholarships") or []:
            await self.s.merge(
                ScholarshipRow(
                    id=seed_id("scholarship", d["slug"], sch["name"]),
                    name=sch["name"][:200],
                    provider="institution",
                    institution_id=inst,
                    country=d["country"],
                    basis="merit",
                    covers=[sch["amount"]] if sch.get("amount") else [],
                    url=str(sch["url"]),
                    source_id=await self.source(sch["url"]),
                    status="published" if verified else "provisional",
                    cycle=sch.get("year"),
                )
            )
            n += 1
        return n

    async def cost_and_aid(self, inst: UUID, d: dict[str, Any], verified: bool) -> None:
        coa, tuition = d.get("intl_coa_usd") or {}, d.get("intl_tuition_usd") or {}
        if coa.get("value") is not None:
            cycle = coa.get("year") or d["year"]
            await self.s.merge(
                CostOfAttendanceRow(
                    id=seed_id("coa", inst, cycle),
                    institution_id=inst,
                    cycle=cycle,
                    currency=coa.get("currency", "USD"),
                    tuition=(
                        Decimal(str(tuition["value"]))
                        if tuition.get("value") is not None
                        else None
                    ),
                    total=Decimal(str(coa["value"])),
                    source_id=await self.source(coa.get("source_url")),
                )
            )
        aid = d.get("aid") or {}
        basis = aid.get("basis") or {}
        merit = aid.get("merit_for_internationals") or {}
        explicit = (aid.get("meets_full_need") or {}).get("value")
        avg = aid.get("avg_aid") or {}
        if basis.get("value") in _AID or avg.get("value") or explicit is not None:
            kind, full = _AID.get(str(basis.get("value")), ("unknown", None))
            cycle = basis.get("year") or avg.get("year") or d["year"]
            await self.s.merge(
                AidPolicyRow(
                    id=seed_id("aid", inst, cycle),
                    institution_id=inst,
                    cycle=cycle,
                    intl_need_based=kind,
                    meets_full_need=full if explicit is None else bool(explicit),
                    merit_available=bool(
                        merit.get("value") or basis["value"] == "merit_only"
                    ),
                    avg_aid=(
                        Decimal(str(avg["value"]))
                        if avg.get("value") is not None
                        else None
                    ),
                    avg_aid_scope=avg.get("scope") if avg.get("value") else None,
                    grant_pct=avg.get("grant_pct"),
                    loan_pct=avg.get("loan_pct"),
                    work_pct=avg.get("work_pct"),
                    source_id=await self.source(
                        avg.get("source_url") or basis.get("source_url")
                    ),
                )
            )

    async def program(self, p: dict[str, Any]) -> None:
        verified = bool(p["verified"])
        cover = p.get("coverage")
        await self.s.merge(
            ScholarshipRow(
                id=seed_id("scholarship", "program", p["country"], p["name"]),
                name=p["name"][:200],
                provider="government",
                institution_id=None,
                country=p["country"],
                basis="government",
                covers=[cover] if cover else [],
                url=str(p["url"]),
                source_id=await self.source(p["url"]),
                status="published" if verified else "provisional",
                cycle=p.get("year"),
            )
        )

    async def owner_of_domain(self, domain: str) -> UUID | None:
        """The id of the institution row that already has this website domain."""
        owner: UUID | None = await self.s.scalar(
            select(InstitutionRow.id).where(
                func.lower(InstitutionRow.website_domain) == domain
            )
        )
        return owner


async def load_catalog(session: AsyncSession, now: dt.datetime) -> LoadReport:
    """Upsert the seed institutions and national programmes; the caller commits.

    A seed institution whose website domain belongs to another row (typically one
    created by staff) is skipped rather than duplicated.
    """
    loader = _Loader(session, now, by_domain(load_org_media()))
    schol = skipped = 0
    seed = load_seed()
    for d in seed:
        domain = normalize_domain(d.get("website_domain"))
        if domain is not None:
            owner = await loader.owner_of_domain(domain)
            if owner is not None and owner != seed_id("institution", d["slug"]):
                skipped += 1
                continue
        schol += await loader.institution(d)
    programs = load_programs()
    for p in programs:
        await loader.program(p)
    await session.flush()
    return LoadReport(len(seed) - skipped, loader.facts, schol + len(programs), skipped)
