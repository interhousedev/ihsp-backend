"""Curator card of an institution.

Routes live under `/v1/admission/staff/catalog/institutions/{id}/*`.
"""

from uuid import UUID

from app.interfaces.http.v1.admission.deps import AnyContext, ContainerDep
from app.interfaces.http.v1.admission.schemas_catalog_card import (
    CardDescriptionIn,
    CardFactOut,
    CardFactsPutIn,
    CardLockOut,
    CardOut,
    CardScholarshipIn,
    CardScholarshipOut,
)
from app.modules.admission.domain.chooser import CatalogScholarship

from fastapi import APIRouter, Response, status

router = APIRouter(
    prefix="/v1/admission/staff/catalog/institutions/{institution_id}",
    tags=["admission"],
)


def _sch(s: CatalogScholarship) -> CardScholarshipOut:
    return CardScholarshipOut(
        id=s.id,
        name=s.name,
        provider=s.provider,
        basis=s.basis,
        country=s.country,
        coverage_pct_min=s.coverage_min,
        coverage_pct_max=s.coverage_max,
        covers=list(s.covers),
        url=s.url,
        cycle=s.cycle,
    )


async def _card(container: ContainerDep, ctx: AnyContext, iid: UUID) -> CardOut:
    card = await container.admission.catalog_card.get(ctx, iid)
    return CardOut(
        lock_version=card.lock_version,
        facts=[
            CardFactOut(
                key=f.key,
                value=f.value,
                source_url=f.source_url,
                year=f.year,
                note=f.note,
                verified=f.verified,
            )
            for f in card.facts
        ],
        scholarships=[_sch(s) for s in card.scholarships],
        description=card.description or {},
    )


async def get_facts(
    institution_id: UUID, container: ContainerDep, ctx: AnyContext
) -> CardOut:
    """Facts, scholarships and description with the lock to send back."""
    return await _card(container, ctx, institution_id)


async def put_facts(
    institution_id: UUID, body: CardFactsPutIn, container: ContainerDep, ctx: AnyContext
) -> CardLockOut:
    """Upsert and delete facts (admin, counselor)."""
    lock = await container.admission.catalog_card.save_facts(
        ctx,
        institution_id,
        {k: v.model_dump() for k, v in body.facts.items()},
        body.remove,
        lock_version=body.lock_version,
    )
    return CardLockOut(lock_version=lock)


async def put_description(
    institution_id: UUID,
    body: CardDescriptionIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> CardLockOut:
    """Replace the per-locale description."""
    lock = await container.admission.catalog_card.save_description(
        ctx, institution_id, body.description, lock_version=body.lock_version
    )
    return CardLockOut(lock_version=lock)


async def list_scholarships(
    institution_id: UUID, container: ContainerDep, ctx: AnyContext
) -> list[CardScholarshipOut]:
    """Scholarships of the institution."""
    return (await _card(container, ctx, institution_id)).scholarships


async def create_scholarship(
    institution_id: UUID,
    body: CardScholarshipIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> CardScholarshipOut:
    """Add a scholarship."""
    sid = await container.admission.catalog_card.create_scholarship(
        ctx,
        institution_id,
        body.model_dump(exclude_unset=True, exclude={"lock_version"}),
        lock_version=body.lock_version,
    )
    rows = (await _card(container, ctx, institution_id)).scholarships
    return next(s for s in rows if s.id == sid)


async def update_scholarship(
    institution_id: UUID,
    scholarship_id: UUID,
    body: CardScholarshipIn,
    container: ContainerDep,
    ctx: AnyContext,
) -> CardScholarshipOut:
    """Overwrite the given scholarship fields."""
    await container.admission.catalog_card.update_scholarship(
        ctx,
        institution_id,
        scholarship_id,
        body.model_dump(exclude_unset=True, exclude={"lock_version"}),
        lock_version=body.lock_version,
    )
    rows = (await _card(container, ctx, institution_id)).scholarships
    return next(s for s in rows if s.id == scholarship_id)


async def delete_scholarship(
    institution_id: UUID,
    scholarship_id: UUID,
    lock_version: int,
    container: ContainerDep,
    ctx: AnyContext,
) -> Response:
    """Remove a scholarship; the lock is a query parameter."""
    await container.admission.catalog_card.delete_scholarship(
        ctx, institution_id, scholarship_id, lock_version=lock_version
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


router.add_api_route(
    "/facts",
    get_facts,
    methods=["GET"],
    response_model=CardOut,
    operation_id="admission_card_get",
)
router.add_api_route(
    "/facts",
    put_facts,
    methods=["PUT"],
    response_model=CardLockOut,
    operation_id="admission_card_put_facts",
)
router.add_api_route(
    "/description",
    put_description,
    methods=["PUT"],
    response_model=CardLockOut,
    operation_id="admission_card_put_description",
)
router.add_api_route(
    "/scholarships",
    list_scholarships,
    methods=["GET"],
    response_model=list[CardScholarshipOut],
    operation_id="admission_card_scholarships",
)
router.add_api_route(
    "/scholarships",
    create_scholarship,
    methods=["POST"],
    response_model=CardScholarshipOut,
    status_code=201,
    operation_id="admission_card_create_scholarship",
)
router.add_api_route(
    "/scholarships/{scholarship_id}",
    update_scholarship,
    methods=["PUT"],
    response_model=CardScholarshipOut,
    operation_id="admission_card_update_scholarship",
)
router.add_api_route(
    "/scholarships/{scholarship_id}",
    delete_scholarship,
    methods=["DELETE"],
    status_code=204,
    operation_id="admission_card_delete_scholarship",
)
