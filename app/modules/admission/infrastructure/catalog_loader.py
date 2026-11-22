"""Idempotent load of the seed catalog into the admission tables (§3.4, §11.1).

Every row has a deterministic UUIDv5 id derived from the seed key (slug, url, fact
key), so a second run updates the same rows instead of adding new ones. A seed
entry whose website domain belongs to another row (typically staff-created) is
not duplicated: its facts are added to that row, never over values already there.
Reviewed seed entries (`verified`) are published with `official` facts; the rest stay
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
from app.modules.admission.ports.media_mirror import MediaMirror

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

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
    """Rows written by one load; `enriched` entries matched an existing domain."""

    institutions: int
    facts: int
    scholarships: int
    enriched: int


class _Loader:
    def __init__(
        self,
        session: AsyncSession,
        now: dt.datetime,
        media: dict[str, OrgMedia],
        mirror: MediaMirror | None = None,
    ) -> None:
        self.mirror = mirror
        self.s = session
        self.now = now
        self.media = media
        self.facts = 0
        self.foreign = False
        """True while writing onto a row the seed did not create."""
        self.sources: set[UUID] = set()

    async def taken(self, model: Any, mine: UUID, *where: ColumnElement[bool]) -> bool:
        """Whether a foreign (non-seed) row matching `where` already exists."""
        if not self.foreign:
            return False
        ids = (await self.s.scalars(select(model.id).where(*where))).all()
        return any(i != mine for i in ids)

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
        if await self.taken(
            FactRow,
            fid,
            FactRow.entity_kind == "institution",
            FactRow.entity_id == inst,
            FactRow.key == key,
        ):
            return  # a staff-entered value of the existing row stays
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

    async def row(
        self, d: dict[str, Any], inst: UUID, owner: UUID | None, verified: bool
    ) -> None:
        """Merge the institution row, or only fill the description of `owner`."""
        if owner is not None:
            row = await self.s.get(InstitutionRow, owner)
            if row is not None and row.description is None:
                row.description = d.get("description")
            if row is not None:
                row.aliases = _merge_aliases(row.aliases, d.get("aliases"))
            return
        org = self.media.get(normalize_domain(d.get("website_domain")) or "")
        logo = d.get("logo_url") or (org.logo_url if org else None)
        cover = d.get("cover_url") or (org.cover_url if org else None)
        if self.mirror is not None:
            logo = await self.mirror.mirror(logo) if logo else None
            cover = await self.mirror.mirror(cover) if cover else None
        existing = await self.s.get(InstitutionRow, inst)
        aliases = _merge_aliases(
            existing.aliases if existing else None, d.get("aliases")
        )
        await self.s.merge(
            InstitutionRow(
                id=inst,
                aliases=aliases,
                slug=d["slug"],
                name=d["name"],
                country=d["country"],
                city=d["city"],
                website_domain=normalize_domain(d.get("website_domain")),
                kind="university",
                status="published" if verified else "provisional",
                logo_url=logo,
                cover_url=cover,
                **_optional(d, "description"),
            )
        )

    async def institution(self, d: dict[str, Any], owner: UUID | None = None) -> int:
        """Write one seed entry; with `owner`, onto that existing row only."""
        inst = owner or seed_id("institution", d["slug"])
        self.foreign = owner is not None
        verified = bool(d["verified"])
        await self.row(d, inst, owner, verified)
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
        await put("focuses", d.get("focuses"))
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
            sid = seed_id("scholarship", d["slug"], sch["name"])
            if await self.taken(
                ScholarshipRow,
                sid,
                ScholarshipRow.institution_id == inst,
                func.lower(ScholarshipRow.name) == sch["name"][:200].lower(),
            ):
                continue
            await self.s.merge(
                ScholarshipRow(
                    id=sid,
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
            cid = seed_id("coa", inst, cycle)
            if not await self.taken(
                CostOfAttendanceRow,
                cid,
                CostOfAttendanceRow.institution_id == inst,
                CostOfAttendanceRow.cycle == cycle,
            ):
                await self.s.merge(
                    CostOfAttendanceRow(
                        id=cid,
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
            pid = seed_id("aid", inst, cycle)
            if await self.taken(
                AidPolicyRow,
                pid,
                AidPolicyRow.institution_id == inst,
                AidPolicyRow.cycle == cycle,
            ):
                return
            await self.s.merge(
                AidPolicyRow(
                    id=pid,
                    institution_id=inst,
                    cycle=cycle,
                    intl_need_based=kind,
                    meets_full_need=full if explicit is None else bool(explicit),
                    merit_available=bool(
                        merit.get("value") or basis.get("value") == "merit_only"
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


async def load_catalog(
    session: AsyncSession, now: dt.datetime, mirror: MediaMirror | None = None
) -> LoadReport:
    """Upsert the seed institutions and national programmes; the caller commits.

    A seed institution whose website domain belongs to another row (typically one
    created by staff) is not duplicated: its facts, scholarships and description
    are added to that row, and nothing already there is overwritten. With a
    `mirror`, logos and covers are copied into our storage first.
    """
    loader = _Loader(session, now, by_domain(load_org_media()), mirror)
    schol = enriched = 0
    seed = load_seed()
    for d in seed:
        domain = normalize_domain(d.get("website_domain"))
        owner = await loader.owner_of_domain(domain) if domain is not None else None
        if owner is not None and owner == seed_id("institution", d["slug"]):
            owner = None
        enriched += owner is not None
        schol += await loader.institution(d, owner)
    programs = load_programs()
    for p in programs:
        await loader.program(p)
    await session.flush()
    return LoadReport(len(seed), loader.facts, schol + len(programs), enriched)


def _merge_aliases(current: list[str] | None, seed: list[str] | None) -> list[str]:
    """Union keeping every existing alias (curator-added included) first."""
    out = list(current or [])
    known = {a.casefold() for a in out}
    for a in seed or []:
        if a.casefold() not in known:
            known.add(a.casefold())
            out.append(a)
    return out


def _optional(d: dict[str, Any], key: str) -> dict[str, Any]:
    """`{key: value}` when the seed has a value, so a merge never blanks the column."""
    return {key: d[key]} if d.get(key) else {}
