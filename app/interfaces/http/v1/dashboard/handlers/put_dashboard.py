"""PUT /v1/me/dashboard."""

from app.interfaces.http.v1.dashboard.deps import ContainerDep, OwnerActor
from app.interfaces.http.v1.dashboard.schemas import (
    DashboardResponse,
    SaveDashboardRequest,
)


async def put_dashboard(
    body: SaveDashboardRequest, container: ContainerDep, actor: OwnerActor
) -> DashboardResponse:
    """Save the dashboard; 409 when the version is not the stored one."""
    layout = await container.dashboard.save_layout.execute(
        user_id=actor.user_id,
        version=body.version,
        widgets=body.widgets,
    )
    return DashboardResponse.from_layout(layout)
