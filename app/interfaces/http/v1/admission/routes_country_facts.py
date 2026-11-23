"""Country facts: students read them, curators manage them (`/v1/admission/...`)."""

from typing import Annotated

from app.interfaces.http.v1.admission.deps import AdmissionCtx, AnyContext, ContainerDep
from app.interfaces.http.v1.admission.schemas_country_facts import (
    CountryFactsListOut,
    CountryFactsOut,
    CountryFactsPutIn,
    CountryOverviewListOut,
    CountryOverviewOut,
    CountryProfileOut,
    CountrySummaryListOut,
    CountrySummaryOut,
)
from app.modules.admission.domain.country_facts import opportunity_fields_of

from fastapi import APIRouter, Query

router = APIRouter(prefix="/v1/admission", tags=["admission"])


async def list_countries(
    container: ContainerDep, ctx: AdmissionCtx
) -> CountryOverviewListOut:
    """Countries with facts or catalog institutions: region, scores, counts."""
    lines = await container.admission.country_facts.overview()
    return CountryOverviewListOut(items=[CountryOverviewOut.of(o) for o in lines])


async def read_country_profile(
    country: str,
    container: ContainerDep,
    ctx: AdmissionCtx,
    fields: Annotated[
        list[str] | None,
        Query(max_length=10, description="The student's study field names."),
    ] = None,
) -> CountryProfileOut:
    """One country: its facts (null when none yet) and ranked catalog institutions."""
    profile = await container.admission.country_facts.profile(country, fields or [])
    return CountryProfileOut.of(profile)


async def read_country_facts(
    container: ContainerDep,
    ctx: AdmissionCtx,
    codes: Annotated[str, Query(description="Comma-separated ISO codes.")],
    fields: Annotated[
        list[str] | None,
        Query(max_length=10, description="The student's study field names."),
    ] = None,
) -> CountryFactsListOut:
    """Facts of up to 30 countries; unverified ones are marked `verified: false`."""
    rows = await container.admission.country_facts.read(codes.split(","))
    return CountryFactsListOut(
        items=[CountryFactsOut.of(r) for r in rows],
        highlight=opportunity_fields_of(fields or []),
    )


async def read_one_country_facts(
    country: str, container: ContainerDep, ctx: AdmissionCtx
) -> CountryFactsOut:
    """The facts of one country."""
    return CountryFactsOut.of(await container.admission.country_facts.read_one(country))


async def list_staff_countries(
    container: ContainerDep,
    ctx: AnyContext,
    q: Annotated[str | None, Query(max_length=20)] = None,
    status: Annotated[str | None, Query(max_length=8)] = None,
) -> CountrySummaryListOut:
    """Every country with coverage and status, filterable (curators only)."""
    lines = await container.admission.country_facts.summaries(
        ctx, query=q, status=status
    )
    return CountrySummaryListOut(items=[CountrySummaryOut.of(s) for s in lines])


async def put_staff_country(
    country: str,
    body: CountryFactsPutIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> CountryFactsOut:
    """Replace the facts of a country; `verified` publishes it as verified."""
    saved = await container.admission.country_facts.save(
        ctx,
        country,
        as_of=body.as_of,
        facts={k: v.model_dump() for k, v in body.facts.items()},
        verified=body.verified,
    )
    return CountryFactsOut.of(saved)


async def verify_staff_country(
    country: str, container: ContainerDep, ctx: AnyContext
) -> CountryFactsOut:
    """Mark the stored facts of a country verified."""
    return CountryFactsOut.of(
        await container.admission.country_facts.verify(ctx, country)
    )


_R = router.add_api_route
_R(
    "/staff/countries",
    list_staff_countries,
    methods=["GET"],
    response_model=CountrySummaryListOut,
    operation_id="admission_staff_countries_list",
)
_R(
    "/staff/countries/{country}",
    put_staff_country,
    methods=["PUT"],
    response_model=CountryFactsOut,
    operation_id="admission_staff_countries_put",
)
_R(
    "/staff/countries/{country}/verify",
    verify_staff_country,
    methods=["POST"],
    response_model=CountryFactsOut,
    operation_id="admission_staff_countries_verify",
)
_R(
    "/country-facts",
    read_country_facts,
    methods=["GET"],
    response_model=CountryFactsListOut,
    operation_id="admission_country_facts_read",
)
_R(
    "/country-facts/{country}",
    read_one_country_facts,
    methods=["GET"],
    response_model=CountryFactsOut,
    operation_id="admission_country_facts_read_one",
)
_R(
    "/countries",
    list_countries,
    methods=["GET"],
    response_model=CountryOverviewListOut,
    operation_id="admission_countries_list",
)
_R(
    "/countries/{country}",
    read_country_profile,
    methods=["GET"],
    response_model=CountryProfileOut,
    responses={404: {"description": "Not an offered ISO country code."}},
    operation_id="admission_countries_read",
)
