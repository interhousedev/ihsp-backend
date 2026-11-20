"""GET /v1/id/me carries no Telegram data; GET /v1/id/me/telegram is the only source."""

from app.interfaces.http.v1.id.account.schemas import UserMeResponse
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.session import LoginSession
from app.modules.identity.domain.user import User
from app.shared.actor import Actor
from tests.identity.support import World

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


def actor_of(user: User, session: LoginSession | None = None) -> Actor:
    """The caller, optionally with a current session."""
    return Actor(
        user_id=user.id,
        roles=frozenset(user.roles),
        session_id=session.id if session else None,
    )


async def test_me_payload_has_no_telegram_key(auth_world: World) -> None:
    """The /me body omits telegram accounts even when the user has links."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555, username="ali")

    view = await auth_world.auth.get_me.execute(actor_of(user))
    payload = UserMeResponse.of(view).model_dump()

    assert payload["id"] == user.id
    assert "telegram" not in payload


async def test_telegram_accounts_are_listed_by_their_own_use_case(
    auth_world: World,
) -> None:
    """GET /v1/id/me/telegram still returns the caller's links."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555, username="ali")

    links = await auth_world.auth.list_telegram_accounts.execute(actor_of(user))

    assert [link.telegram_user_id for link in links] == [555]
