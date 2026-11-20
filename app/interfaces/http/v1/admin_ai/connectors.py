"""Routes /v1/admin/ai/connectors and /pipelines (admin only; mounted by router.py)."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.admin_ai.connectors_schemas import (
    ConnectorBody,
    ConnectorOut,
    ConnectorPatchBody,
    ConnectorsResponse,
    ConnectorTestOut,
    PipelineOut,
    PipelineRouteBody,
    PipelinesResponse,
)
from app.modules.ai.domain.connectors import ConnectorKind
from app.modules.ai.wiring import ConnectorServices
from app.shared.actor import Actor, Role

from fastapi import APIRouter, Depends, Response, status

router = APIRouter()

ContainerDep = Annotated[Container, Depends(get_container)]
AdminActor = Annotated[Actor, Depends(require_roles(Role.ADMIN))]


def _services(container: Container) -> ConnectorServices:
    services = container.ai.connectors
    if services is None:  # every composition root with AI builds them
        raise RuntimeError("connector services are not wired")
    return services


@router.get("/connectors", response_model=ConnectorsResponse)
async def list_connectors(
    container: ContainerDep, actor: AdminActor
) -> ConnectorsResponse:
    """Every connector: made from the environment or added here (no keys)."""
    rows = await _services(container).connectors.list(actor)
    return ConnectorsResponse(
        items=[ConnectorOut.of(row) for row in rows], kinds=list(ConnectorKind)
    )


@router.post(
    "/connectors", response_model=ConnectorOut, status_code=status.HTTP_201_CREATED
)
async def add_connector(
    body: ConnectorBody, container: ContainerDep, actor: AdminActor
) -> ConnectorOut:
    """Add a connector; its key is written to Vault first and never read back."""
    row = await _services(container).connectors.create(
        actor,
        id=body.id,
        kind=body.kind,
        title=body.title,
        base_url=body.base_url,
        api_key=body.api_key.get_secret_value() if body.api_key else None,
        headers=body.headers,
    )
    return ConnectorOut.of(row)


@router.patch("/connectors/{connector_id}", response_model=ConnectorOut)
async def change_connector(
    connector_id: str,
    body: ConnectorPatchBody,
    container: ContainerDep,
    actor: AdminActor,
) -> ConnectorOut:
    """Change a connector; a connector of the environment gets an override row."""
    row = await _services(container).connectors.update(
        actor,
        connector_id,
        title=body.title,
        base_url=body.base_url,
        enabled=body.enabled,
        api_key=body.api_key.get_secret_value() if body.api_key else None,
    )
    return ConnectorOut.of(row)


@router.delete(
    "/connectors/{connector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def remove_connector(
    connector_id: str, container: ContainerDep, actor: AdminActor
) -> Response:
    """Remove a connector and its key; a built-in one returns to the environment."""
    await _services(container).connectors.delete(actor, connector_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/connectors/{connector_id}/test", response_model=ConnectorTestOut)
async def test_connector(
    connector_id: str, container: ContainerDep, actor: AdminActor
) -> ConnectorTestOut:
    """Ask the provider something tiny; the answer never contains the key."""
    result = await _services(container).connectors.test(actor, connector_id)
    return ConnectorTestOut.of(result)


@router.get("/pipelines", response_model=PipelinesResponse)
async def list_pipelines(
    container: ContainerDep, actor: AdminActor
) -> PipelinesResponse:
    """Every pipeline with its tasks, runtime route and what its calls use."""
    views = await _services(container).pipelines.list(actor)
    return PipelinesResponse(items=[PipelineOut.of(view) for view in views])


@router.put("/pipelines/{pipeline}", response_model=PipelineOut)
async def route_pipeline(
    pipeline: str,
    body: PipelineRouteBody,
    container: ContainerDep,
    actor: AdminActor,
) -> PipelineOut:
    """Route a pipeline to a connector, model and effort; applies within 30 s."""
    view = await _services(container).pipelines.put(
        actor,
        pipeline,
        connector_id=body.connector_id,
        model=body.model,
        reasoning_effort=body.reasoning_effort,
    )
    return PipelineOut.of(view)


@router.delete(
    "/pipelines/{pipeline}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def reset_pipeline(
    pipeline: str, container: ContainerDep, actor: AdminActor
) -> Response:
    """Send the pipeline back to the environment's values."""
    await _services(container).pipelines.delete(actor, pipeline)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
