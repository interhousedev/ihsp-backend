"""GET /v1/id/me: the caller's account."""

from app.interfaces.http.v1.id.account.schemas import UserMeResponse
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep


async def get_me(actor: ActorDep, auth: AuthDep) -> UserMeResponse:
    """Profile, security settings, preferences and Telegram accounts."""
    return UserMeResponse.of(await auth.get_me.execute(actor))
