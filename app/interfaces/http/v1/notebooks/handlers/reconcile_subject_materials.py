"""POST .../reconcile: check that all lesson materials are in the subject notebooks."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import AdminActor, Notebooks
from app.interfaces.http.v1.notebooks.schemas_admin_materials import (
    ReconcileMaterialsResponse,
)


async def reconcile_admin_subject_materials(
    subject_id: UUID, notebooks: Notebooks, actor: AdminActor
) -> ReconcileMaterialsResponse:
    """Sync every student's subject notebook of the subject, now; report the totals."""
    result = await notebooks.reconcile_subject_materials.execute(subject_id)
    return ReconcileMaterialsResponse.from_result(result)
