"""GET /v1/id/me/sessions: active devices."""

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep
from app.interfaces.http.v1.id.schemas import SessionItemResponse


async def get_sessions(actor: ActorDep, auth: AuthDep) -> list[SessionItemResponse]:
    """Sessions with the current one marked."""
    views = await auth.list_sessions.execute(actor)
    return [SessionItemResponse.of(view) for view in views]
