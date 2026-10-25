"""GET /v1/me/dashboard."""

from app.interfaces.http.v1.dashboard.deps import ContainerDep, OwnerActor
from app.interfaces.http.v1.dashboard.schemas import DashboardResponse


async def get_dashboard(
    container: ContainerDep, actor: OwnerActor
) -> DashboardResponse:
    """Return the user's dashboard, or the default one at version 0."""
    layout = await container.dashboard.get_layout.execute(user_id=actor.user_id)
    return DashboardResponse.from_layout(layout)
