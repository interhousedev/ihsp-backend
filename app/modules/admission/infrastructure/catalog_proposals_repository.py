"""SQL repository of catalog proposals."""

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from app.modules.admission.domain.catalog_proposals import CatalogProposal
from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.domain.intl_facts import CleanFact, clean_facts, to_row
from app.modules.admission.infrastructure.catalog_loader import _AID
from app.modules.admission.infrastructure.orm.catalog import (
    AidPolicyRow,
    CatalogProposalRow,
    CostOfAttendanceRow,
    FactRow,
    InstitutionRow,
    ScholarshipRow,
    SourceRow,
)
from app.shared.ids import new_id

from sqlalchemy import (
    ColumnElement,
    case,
    exists,
    func,
    literal_column,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

_TARGETS: dict[str, Any] = {
    "institution": InstitutionRow,
    "scholarship": ScholarshipRow,
}

_SUBMIT_LOCK_KEY = 0x4348_5052_4F50
"""Advisory-lock key of catalog proposal submission (ASCII `CHPROP`)."""


def _fold_sql(expr: Any) -> ColumnElement[str]:
    """SQL twin of `fold_name`: NFC, collapsed whitespace, trimmed, lower-cased."""
    return func.lower(
        func.btrim(
            func.regexp_replace(
                func.normalize(expr, literal_column("NFC")), r"\s+", " ", "g"
            )
        )
    )


def _proposal(r: CatalogProposalRow) -> CatalogProposal:
    payload = dict(r.payload)
    facts = payload.pop("facts", None) or {}
    supp_prompts = payload.pop("supp_prompts", None) or []
    return CatalogProposal(
        id=r.id,
        kind=r.kind,  # type: ignore[arg-type]
        target_id=r.target_id,
        payload=payload,
        facts=dict(facts),
        supp_prompts=list(supp_prompts),
        source_url=r.source_url,
        note=r.note,
        status=r.status,  # type: ignore[arg-type]
        proposed_by=r.proposed_by,
        created_at=r.created_at,
        lock_version=r.lock_version,
        reviewed_by=r.reviewed_by,
        reviewed_at=r.reviewed_at,
        review_note=r.review_note,
        applied_id=r.applied_id,
    )


class SqlCatalogProposalRepository:
    """Proposals and the write of an approved one into the catalog."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def add(self, proposal: CatalogProposal) -> CatalogProposal:
        """Insert a pending proposal."""
        row = CatalogProposalRow(
            id=proposal.id,
            kind=proposal.kind,
            target_id=proposal.target_id,
            payload={
                **proposal.payload,
                **({"facts": proposal.facts} if proposal.facts else {}),
                **(
                    {"supp_prompts": proposal.supp_prompts}
                    if proposal.supp_prompts
                    else {}
                ),
            },
            source_url=proposal.source_url,
            note=proposal.note,
            status="pending",
            proposed_by=proposal.proposed_by,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _proposal(row)

    async def get(self, proposal_id: UUID) -> CatalogProposal | None:
        """Return one proposal."""
        row = await self._s.get(CatalogProposalRow, proposal_id)
        return _proposal(row) if row else None

    async def list(
        self, *, status: str | None = None, proposed_by: UUID | None = None
    ) -> list[CatalogProposal]:
        """Return proposals, newest first."""
        q = select(CatalogProposalRow).order_by(CatalogProposalRow.created_at.desc())
        if status is not None:
            q = q.where(CatalogProposalRow.status == status)
        if proposed_by is not None:
            q = q.where(CatalogProposalRow.proposed_by == proposed_by)
        return [_proposal(r) for r in await self._s.scalars(q)]

    async def target_exists(self, kind: str, target_id: UUID) -> bool:
        """Return whether the row to edit exists."""
        return await self._s.get(_TARGETS[kind], target_id) is not None

    async def set_logo(
        self, institution_id: UUID, *, zoom: float | None, fit: str | None
    ) -> bool:
        """Set the given logo fields of an institution; False when it is unknown."""
        row = await self._s.get(InstitutionRow, institution_id)
        if row is None:
            return False
        if zoom is not None:
            row.logo_zoom = zoom
        if fit is not None:
            row.logo_fit = fit
        await self._s.flush()
        return True

    async def lock_submissions(self) -> None:
        """Take the transaction-scoped advisory lock of catalog submissions."""
        await self._s.execute(select(func.pg_advisory_xact_lock(_SUBMIT_LOCK_KEY)))

    async def find_duplicate(
        self, names: Sequence[str], website_domain: str | None
    ) -> tuple[Literal["institution", "proposal"], UUID] | None:
        """Find an institution by name, alias or domain, or a pending create."""
        if not names and not website_domain:
            return None
        inst_alias = (
            func.unnest(InstitutionRow.aliases)
            .table_valued("alias")
            .render_derived(name="inst_alias")
        )
        conds: list[ColumnElement[bool]] = [
            _fold_sql(InstitutionRow.name).in_(names),
            exists(
                select(1)
                .select_from(inst_alias)
                .where(_fold_sql(inst_alias.c.alias).in_(names))
            ),
        ]
        if website_domain:
            conds.append(func.lower(InstitutionRow.website_domain) == website_domain)
        found = await self._s.scalar(
            select(InstitutionRow.id)
            .where(InstitutionRow.status != "archived", or_(*conds))
            .limit(1)
        )
        if found is not None:
            return "institution", found
        payload_aliases = CatalogProposalRow.payload["aliases"]
        safe_aliases = case(
            (func.jsonb_typeof(payload_aliases) == "array", payload_aliases),
            else_=text("'[]'::jsonb"),
        )
        pending_alias = (
            func.jsonb_array_elements_text(safe_aliases)
            .table_valued("alias")
            .render_derived(name="pending_alias")
        )
        pending_conds: list[ColumnElement[bool]] = [
            _fold_sql(CatalogProposalRow.payload["name"].astext).in_(names),
            exists(
                select(1)
                .select_from(pending_alias)
                .where(_fold_sql(pending_alias.c.alias).in_(names))
            ),
        ]
        if website_domain:
            pending_conds.append(
                func.lower(CatalogProposalRow.payload["website_domain"].astext)
                == website_domain
            )
        pending = await self._s.scalar(
            select(CatalogProposalRow.id)
            .where(
                CatalogProposalRow.kind == "institution",
                CatalogProposalRow.status == "pending",
                CatalogProposalRow.target_id.is_(None),
                or_(*pending_conds),
            )
            .limit(1)
        )
        return ("proposal", pending) if pending is not None else None

    async def apply(
        self, proposal: CatalogProposal, *, reviewer_id: UUID, now: dt.datetime
    ) -> UUID:
        """Create or update the catalog row and its facts, and publish them."""
        source = SourceRow(
            id=new_id(), kind="manual", url=proposal.source_url, redistributable=False
        )
        self._s.add(source)
        model = _TARGETS[proposal.kind]
        values = {**proposal.payload, "source_id": source.id}
        if proposal.kind == "institution":
            values.pop("source_id")
        values["status"] = "published"
        if proposal.target_id is not None:
            row = await self._s.get(model, proposal.target_id)
            if row is None:
                raise AdmissionConflictError()
            for k, v in values.items():
                setattr(row, k, v)
        else:
            row = model(id=new_id(), **values)
            self._s.add(row)
        await self._s.flush()
        if proposal.facts:
            await self._apply_facts(row.id, proposal, reviewer_id, now)
        return row.id  # type: ignore[no-any-return]

    async def _apply_facts(
        self,
        institution_id: UUID,
        proposal: CatalogProposal,
        reviewer_id: UUID,
        now: dt.datetime,
    ) -> None:
        """Upsert each fact in place and mirror cost and aid into their tables."""
        sources: dict[str, UUID] = {}
        for key, fact in clean_facts(proposal.facts).items():
            if fact.source_url not in sources:
                src = SourceRow(
                    id=new_id(),
                    kind="manual",
                    url=fact.source_url,
                    redistributable=False,
                )
                self._s.add(src)
                sources[fact.source_url] = src.id
            source_id = sources[fact.source_url]
            value, unit = to_row(fact)
            if key == "deadlines":
                value = [{**d, "source_url": fact.source_url} for d in value]
            await self._upsert_fact(
                institution_id, fact, value, unit, source_id, reviewer_id, now
            )
            await self._mirror(institution_id, fact, value, source_id)
        await self._s.flush()

    async def _upsert_fact(
        self,
        institution_id: UUID,
        fact: CleanFact,
        value: Any,
        unit: str | None,
        source_id: UUID,
        reviewer_id: UUID,
        now: dt.datetime,
    ) -> None:
        rows = list(
            await self._s.scalars(
                select(FactRow)
                .where(
                    FactRow.entity_kind == "institution",
                    FactRow.entity_id == institution_id,
                    FactRow.key == fact.key,
                    FactRow.status == "published",
                )
                .order_by(FactRow.cycle.desc().nulls_last(), FactRow.updated_at.desc())
            )
        )
        if rows:
            row = rows[0]
            for other in rows[1:]:
                other.status = "stale"
        else:
            row = FactRow(
                id=new_id(),
                entity_kind="institution",
                entity_id=institution_id,
                key=fact.key,
            )
            self._s.add(row)
        row.value = value
        row.unit = unit
        row.cycle = fact.year
        row.source_id = source_id
        row.excerpt = fact.note[:300] if fact.note else None
        row.checked_at = now
        row.reviewer_id = reviewer_id
        row.confidence = "manual"
        row.status = "published"

    async def _mirror(
        self, institution_id: UUID, fact: CleanFact, value: Any, source_id: UUID
    ) -> None:
        """Keep the cost and aid tables, which the chooser reads, in step."""
        key = fact.key
        if key in ("intl_coa_usd", "intl_tuition_usd"):
            await self._mirror_cost(institution_id, fact, value, source_id)
        elif key in ("aid_basis", "meets_full_need", "merit_for_internationals"):
            await self._mirror_aid(institution_id, fact, value, source_id)

    async def _mirror_cost(
        self, institution_id: UUID, fact: CleanFact, value: Any, source_id: UUID
    ) -> None:
        cycle = fact.year
        coa = await self._s.scalar(
            select(CostOfAttendanceRow).where(
                CostOfAttendanceRow.institution_id == institution_id,
                CostOfAttendanceRow.cycle == cycle,
            )
        )
        if coa is None:
            coa = CostOfAttendanceRow(
                id=new_id(),
                institution_id=institution_id,
                cycle=cycle,
                currency="USD",
            )
            self._s.add(coa)
        coa.currency = "USD"
        coa.source_id = source_id
        if fact.key == "intl_coa_usd":
            coa.total = Decimal(str(value))
        else:
            coa.tuition = Decimal(str(value))

    async def _mirror_aid(
        self, institution_id: UUID, fact: CleanFact, value: Any, source_id: UUID
    ) -> None:
        key, cycle = fact.key, fact.year
        aid = await self._s.scalar(
            select(AidPolicyRow).where(
                AidPolicyRow.institution_id == institution_id,
                AidPolicyRow.cycle == cycle,
            )
        )
        if aid is None:
            aid = AidPolicyRow(
                id=new_id(),
                institution_id=institution_id,
                cycle=cycle,
                intl_need_based="unknown",
                merit_available=False,
            )
            self._s.add(aid)
        aid.source_id = source_id
        if key == "aid_basis" and value in _AID:
            aid.intl_need_based, full = _AID[value]
            if full is not None:
                aid.meets_full_need = full
            if value == "merit_only":
                aid.merit_available = True
        elif key == "meets_full_need":
            aid.meets_full_need = bool(value)
        elif key == "merit_for_internationals":
            aid.merit_available = bool(value)

    async def save_review(
        self, proposal: CatalogProposal, *, expected_lock: int
    ) -> CatalogProposal:
        """Write the review; conflict if `lock_version` moved."""
        result = await self._s.execute(
            update(CatalogProposalRow)
            .where(
                CatalogProposalRow.id == proposal.id,
                CatalogProposalRow.lock_version == expected_lock,
                CatalogProposalRow.status == "pending",
            )
            .values(
                status=proposal.status,
                reviewed_by=proposal.reviewed_by,
                reviewed_at=proposal.reviewed_at,
                review_note=proposal.review_note,
                applied_id=proposal.applied_id,
                lock_version=expected_lock + 1,
            )
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AdmissionConflictError()
        row = await self._s.get(CatalogProposalRow, proposal.id)
        await self._s.refresh(row)
        assert row is not None
        return _proposal(row)
