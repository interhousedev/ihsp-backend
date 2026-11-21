"""SQL repository of the staff catalog tables."""

from typing import Any
from uuid import UUID

from app.modules.admission.domain.catalog_staff import (
    InstitutionPage,
    StaffInstitution,
)
from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.domain.opportunities import Opportunity, OpportunityDraft
from app.modules.admission.infrastructure.orm.applications import (
    DeckDecisionRow,
    ListEntryRow,
)
from app.modules.admission.infrastructure.orm.catalog import FactRow, InstitutionRow
from app.modules.admission.infrastructure.orm.essay_flow import EssaySlotRow
from app.modules.admission.infrastructure.orm.essay_reviews import EssayReviewRow
from app.modules.admission.infrastructure.orm.item_opportunity import (
    ItemOpportunityLinkRow,
)
from app.modules.admission.infrastructure.orm.matching import DecisionRow
from app.modules.admission.infrastructure.orm.opportunities import (
    OpportunityPlanEntryRow,
    OpportunityRow,
)
from app.modules.admission.infrastructure.orm.outcomes import ApplicationOutcomeRow
from app.modules.admission.infrastructure.orm.uni_chat import UniChatRow
from app.shared.ids import new_id

from sqlalchemy import ColumnElement, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

_STUDENT_TABLES = (
    ListEntryRow,
    DeckDecisionRow,
    EssaySlotRow,
    EssayReviewRow,
    UniChatRow,
    DecisionRow,
    ApplicationOutcomeRow,
)
"""Student-owned tables that point at an institution."""


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _institution(r: InstitutionRow, in_use: bool) -> StaffInstitution:
    return StaffInstitution(
        id=r.id,
        name=r.name,
        name_local=r.name_local,
        country=r.country,
        city=r.city,
        website_domain=r.website_domain,
        kind=r.kind,
        size_band=r.size_band,
        setting=r.setting,
        languages=tuple(r.languages or ()),
        aliases=tuple(r.aliases or ()),
        status=r.status,  # type: ignore[arg-type]
        logo_url=r.logo_url,
        cover_url=r.cover_url,
        logo_zoom=r.logo_zoom,
        logo_fit=r.logo_fit,
        created_at=r.created_at,
        updated_at=r.updated_at,
        lock_version=r.lock_version,
        in_use=in_use,
    )


class SqlCatalogStaffRepository:
    """Searchable lists and hard deletes for the catalog curators."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def search_opportunities(
        self,
        *,
        query: str | None,
        kind: str | None,
        archived: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Opportunity], int]:
        """One page of entries and the total of the filter."""
        conds: list[ColumnElement[bool]] = []
        if query:
            like = _like(query)
            conds.append(
                or_(
                    OpportunityRow.title.ilike(like),
                    OpportunityRow.payload["provider"].astext.ilike(like),
                )
            )
        if kind is not None:
            conds.append(OpportunityRow.kind == kind)
        if archived is not None:
            conds.append(OpportunityRow.archived.is_(archived))
        total = await self._s.scalar(
            select(func.count()).select_from(OpportunityRow).where(*conds)
        )
        rows = await self._s.scalars(
            select(OpportunityRow)
            .where(*conds)
            .order_by(OpportunityRow.updated_at.desc(), OpportunityRow.id)
            .offset(offset)
            .limit(limit)
        )
        items = [
            Opportunity(
                id=r.id,
                draft=OpportunityDraft.from_payload(r.payload),
                created_by=r.created_by,
                created_at=r.created_at,
                updated_at=r.updated_at,
                archived=r.archived,
                lock_version=r.lock_version,
            )
            for r in rows
        ]
        return items, int(total or 0)

    async def opportunity_in_use(self, opportunity_id: UUID) -> bool:
        """Whether a plan entry or an activity link refers to the entry."""
        plan = await self._s.scalar(
            select(OpportunityPlanEntryRow.id)
            .where(OpportunityPlanEntryRow.opportunity_id == opportunity_id)
            .limit(1)
        )
        if plan is not None:
            return True
        link = await self._s.scalar(
            select(ItemOpportunityLinkRow.item_id)
            .where(ItemOpportunityLinkRow.opportunity_id == opportunity_id)
            .limit(1)
        )
        return link is not None

    async def delete_opportunity(self, opportunity_id: UUID) -> None:
        """Remove an entry (comments cascade)."""
        await self._s.execute(
            delete(OpportunityRow).where(OpportunityRow.id == opportunity_id)
        )

    async def _used_ids(self, ids: list[UUID]) -> set[UUID]:
        used: set[UUID] = set()
        if not ids:
            return used
        for table in _STUDENT_TABLES:
            col = table.institution_id
            used.update(await self._s.scalars(select(col).where(col.in_(ids))))
        return used

    async def search_institutions(
        self,
        *,
        query: str | None,
        country: str | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> InstitutionPage:
        """One page of institutions, newest edit first."""
        conds: list[ColumnElement[bool]] = []
        if query:
            like = _like(query)
            conds.append(
                or_(
                    InstitutionRow.name.ilike(like),
                    InstitutionRow.name_local.ilike(like),
                    InstitutionRow.city.ilike(like),
                    InstitutionRow.website_domain.ilike(like),
                )
            )
        if country is not None:
            conds.append(InstitutionRow.country == country.upper())
        if status is not None:
            conds.append(InstitutionRow.status == status)
        total = await self._s.scalar(
            select(func.count()).select_from(InstitutionRow).where(*conds)
        )
        rows = list(
            await self._s.scalars(
                select(InstitutionRow)
                .where(*conds)
                .order_by(InstitutionRow.name, InstitutionRow.id)
                .offset(offset)
                .limit(limit)
            )
        )
        used = await self._used_ids([r.id for r in rows])
        country_col = InstitutionRow.country
        countries = list(
            await self._s.scalars(select(country_col).distinct().order_by(country_col))
        )
        return InstitutionPage(
            items=[_institution(r, r.id in used) for r in rows],
            total=int(total or 0),
            countries=countries,
        )

    async def get_institution(self, institution_id: UUID) -> StaffInstitution | None:
        """One institution of any status."""
        row = await self._s.get(InstitutionRow, institution_id)
        if row is None:
            return None
        return _institution(row, institution_id in await self._used_ids([row.id]))

    async def create_institution(self, values: dict[str, Any]) -> UUID:
        """Insert an institution."""
        row = InstitutionRow(id=new_id(), **values)
        self._s.add(row)
        await self._s.flush()
        return row.id

    async def update_institution(
        self, institution_id: UUID, values: dict[str, Any], *, expected_lock: int
    ) -> bool:
        """Overwrite the given columns under the optimistic lock."""
        row = await self._s.get(InstitutionRow, institution_id)
        if row is None:
            return False
        if row.lock_version != expected_lock:
            raise AdmissionConflictError()
        for key, value in values.items():
            setattr(row, key, value)
        row.lock_version = row.lock_version + 1
        await self._s.flush()
        return True

    async def institution_in_use(self, institution_id: UUID) -> bool:
        """Whether student data refers to the institution."""
        return institution_id in await self._used_ids([institution_id])

    async def delete_institution(self, institution_id: UUID) -> None:
        """Remove an institution with its facts; catalog rows cascade."""
        await self._s.execute(
            delete(FactRow).where(
                FactRow.entity_kind == "institution",
                FactRow.entity_id == institution_id,
            )
        )
        await self._s.execute(
            delete(InstitutionRow).where(InstitutionRow.id == institution_id)
        )
