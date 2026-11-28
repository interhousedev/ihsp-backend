"""Catalog tools (universities, opportunities, countries) and the consent read.

The catalog is shared by applicants and staff; it holds no personal data. Saving
an opportunity to the student's plan is `plan_opportunity` (plans tools).
"""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.admission.tools.common import applicant, lazy_services, services
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.opportunities import CatalogFilter
from app.modules.admission.domain.chooser import CatalogFilters, CatalogInstitution
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.modules.admission.domain.opportunities import OpportunityKind
from app.shared.mcp_scopes import ADMISSION_APPLICANT_ROLES, ADMISSION_ROLES

from pydantic import Field

Query = Annotated[
    str | None, Field(max_length=100, description="Words of the name or title.")
]
Country = Annotated[
    str | None, Field(max_length=300, description="ISO country code, e.g. US.")
]
Limit = Annotated[int, Field(ge=1, le=50, description="Page size.")]


async def _member(kit: ToolKit) -> AdmissionContext:
    """The context of an applicant or admission staff member; others are refused."""
    ctx: AdmissionContext = await services(kit).actor.execute(current_actor())
    if not (ctx.admission.is_applicant or ctx.admission.is_staff):
        raise AdmissionForbiddenError(params={"permission": "catalog:read"})
    return ctx


def _summary(i: CatalogInstitution) -> dict[str, Any]:
    return {
        "id": str(i.id),
        "name": i.name,
        "name_local": i.name_local,
        "country": i.country,
        "city": i.city,
        "cost_of_attendance": i.coa_total,
        "currency": i.coa_currency,
        "aid_basis": i.aid_basis,
        "merit_available": i.merit_available,
        "scholarship_count": i.scholarship_count,
        "website_domain": i.website_domain,
    }


def register(kit: ToolKit) -> None:
    """Register the catalog and consent tools."""
    adm = lazy_services(kit)

    @kit.tool("catalog:read", roles=ADMISSION_ROLES)
    async def search_universities(
        q: Query = None,
        country: Country = None,
        field: Annotated[
            str | None, Field(max_length=100, description="Field of study key.")
        ] = None,
        cursor: Annotated[int, Field(ge=0, description="From next_cursor.")] = 0,
        limit: Limit = 20,
    ) -> dict[str, Any]:
        """Universities of the catalog by name, country or field of study.

        Next: get_university for facts and deadlines of one result.
        """
        await _member(kit)
        page = await adm.catalog.search(
            CatalogFilters(q=q, country=country, field=field),
            cursor=cursor,
            limit=limit,
        )
        return {
            "items": [_summary(i) for i in page.items],
            "next_cursor": page.next_cursor,
        }

    @kit.tool("catalog:read", roles=ADMISSION_ROLES)
    async def get_university(
        university_id: Annotated[
            UUID, Field(description="Id from search_universities.")
        ],
    ) -> dict[str, Any]:
        """One university with its cited facts, deadlines and aid profile."""
        await _member(kit)
        return {"university": await adm.catalog.institution(university_id)}

    @kit.tool("catalog:read", roles=ADMISSION_ROLES)
    async def search_opportunities(
        q: Query = None,
        kind: OpportunityKind | None = None,
        country: Country = None,
        grade: Annotated[int | None, Field(ge=1, le=20)] = None,
        online: bool | None = None,
        free: bool | None = None,
        page: Annotated[int, Field(ge=1)] = 1,
        size: Limit = 20,
    ) -> dict[str, Any]:
        """Published opportunities: summer programs, competitions, courses, more.

        A student who named a field of study sees matching entries first.
        Next: get_opportunity, then plan_opportunity to save one to the plan.
        """
        ctx = await _member(kit)
        found = await adm.opportunities.catalog(
            CatalogFilter(
                query=q,
                kind=kind,
                country=country,
                grade=grade,
                online=online,
                free=free,
                page=page,
                size=size,
            ),
            ctx,
        )
        return {
            "items": [
                {"id": str(o.id), "title": o.draft.title, "kind": o.draft.kind}
                for o in found.items
            ],
            "total": found.total,
            "page": found.page,
        }

    @kit.tool("catalog:read", roles=ADMISSION_ROLES)
    async def get_opportunity(
        opportunity_id: Annotated[
            UUID, Field(description="Id from search_opportunities.")
        ],
    ) -> dict[str, Any]:
        """One published opportunity with all its details."""
        await _member(kit)
        found = await adm.opportunities.get(opportunity_id)
        return {"id": str(found.id), "opportunity": found.draft}

    @kit.tool("catalog:read", roles=ADMISSION_ROLES)
    async def get_country(
        country: Annotated[
            str, Field(min_length=2, max_length=2, description="ISO code, e.g. DE.")
        ],
    ) -> dict[str, Any]:
        """Study facts of one country: costs, visas, work rights, language."""
        await _member(kit)
        return {"country": await adm.country_facts.read_one(country)}

    @kit.tool("consents:read", roles=ADMISSION_APPLICANT_ROLES)
    async def list_consents() -> dict[str, Any]:
        """The student's purpose consents; without the AI purpose AI tools stop."""
        ctx = await applicant(kit)
        state = await adm.privacy.consent(ctx)
        return {
            "grants": state.grants,
            "non_ai_mode": state.non_ai_mode,
            "pending": state.pending,
        }
