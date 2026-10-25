"""Admin routes: check that all lesson materials are in the subject notebooks (async).

POST answers 202 with a job id; GET .../{job_id} reports the totals once it runs.
"""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.notebooks.deps import AdminActor, Notebooks
from app.interfaces.http.v1.notebooks.reconcile_jobs import (
    reconcile_status,
    start_reconcile,
)
from app.interfaces.http.v1.notebooks.schemas_admin_materials import (
    ReconcileJobAccepted,
    ReconcileJobStatus,
)

from fastapi import Depends


async def reconcile_admin_subject_materials(
    subject_id: UUID,
    notebooks: Notebooks,
    actor: AdminActor,
    container: Annotated[Container, Depends(get_container)],
) -> ReconcileJobAccepted:
    """Queue the sync of every student's subject notebook of the subject; answer 202."""
    return await start_reconcile(container, subject_id, None, actor.user_id)


async def get_admin_reconcile_status(
    subject_id: UUID,
    job_id: str,
    notebooks: Notebooks,
    actor: AdminActor,
    container: Annotated[Container, Depends(get_container)],
) -> ReconcileJobStatus:
    """The totals of a reconcile job (any admin may read any of them)."""
    return await reconcile_status(container, job_id, started_by=None)
