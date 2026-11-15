"""Routes /v1/admin/migration (Administration only; start and rollback need step-up)."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_migration.schemas import (
    MigrationStatusResponse,
    RollbackBody,
    StartMigrationBody,
)
from app.modules.admin.domain.migration import MigrationState
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends

router = APIRouter(prefix="/v1/admin/migration", tags=["admin-migration"])

ContainerDep = Annotated[Container, Depends(get_container)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]


def _response(
    container: Container, state: MigrationState | None
) -> MigrationStatusResponse:
    service = container.admin.migration
    return MigrationStatusResponse.of(
        state,
        configured=service.configured(),
        stale=state is not None and service.is_stale(state),
    )


@router.get("", response_model=MigrationStatusResponse)
async def get_migration(
    container: ContainerDep, actor: AdminActor
) -> MigrationStatusResponse:
    """Return the migration phase and the progress of its steps."""
    state = await container.admin.migration.status(actor)
    return _response(container, state)


@router.post("/start", response_model=MigrationStatusResponse)
async def start_migration(
    body: StartMigrationBody, container: ContainerDep, actor: AdminActor
) -> MigrationStatusResponse:
    """Queue the migration; the platform turns read-only at once."""
    state = await container.admin.migration.start(
        actor,
        target_host=body.target_host,
        target_port=body.target_port,
        pairing_token=body.pairing_token.get_secret_value(),
        target_url=body.target_url,
        otp_code=body.otp_code,
    )
    return _response(container, state)


@router.post("/rollback", response_model=MigrationStatusResponse)
async def rollback_migration(
    body: RollbackBody, container: ContainerDep, actor: AdminActor
) -> MigrationStatusResponse:
    """Leave maintenance mode; the source data was never touched."""
    state = await container.admin.migration.rollback(actor, otp_code=body.otp_code)
    return _response(container, state)
