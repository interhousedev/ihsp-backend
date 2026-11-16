"""Routes of item proofs (`/v1/admission/items/{item_id}/proofs`)."""

from datetime import datetime
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.modules.admission.domain.help_proofs import Proof

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class ProofIn(BaseModel):
    """One proof: a link, an uploaded file or pasted text."""

    url: str | None = Field(default=None, max_length=2048)
    file_id: UUID | None = None
    pasted_text: str | None = Field(default=None, max_length=20000)


class ProofOut(BaseModel):
    """A proof and its check status."""

    id: UUID
    item_id: UUID
    kind: str
    status: str
    url: str | None
    file_id: UUID | None
    fetched_at: datetime | None
    title: str | None = None

    @classmethod
    def of(cls, p: Proof, title: str | None = None) -> "ProofOut":
        """Build from the domain proof."""
        return cls(
            id=p.id,
            item_id=p.item_id,
            kind=p.kind,
            status=p.status,
            url=p.url,
            file_id=p.file_id,
            fetched_at=p.fetched_at,
            title=title,
        )


class ProofListOut(BaseModel):
    """Proofs of one item."""

    items: list[ProofOut]


async def add_proof(
    item_id: UUID, body: ProofIn, container: ContainerDep, ctx: AdmissionCtx
) -> ProofOut:
    """Attach a link, file or text; links are checked for reachability."""
    res = await container.admission.proofs.add(
        ctx,
        item_id,
        url=body.url,
        file_id=body.file_id,
        pasted_text=body.pasted_text,
    )
    return ProofOut.of(res.proof, res.title)


async def list_proofs(
    item_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ProofListOut:
    """The proofs of an item."""
    rows = await container.admission.proofs.list(ctx, item_id)
    return ProofListOut(items=[ProofOut.of(p) for p in rows])


router.add_api_route(
    "/items/{item_id}/proofs",
    add_proof,
    methods=["POST"],
    response_model=ProofOut,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="admission_add_proof",
)
router.add_api_route(
    "/items/{item_id}/proofs",
    list_proofs,
    methods=["GET"],
    response_model=ProofListOut,
    operation_id="admission_list_proofs",
)
