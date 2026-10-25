"""ID-16, GEN-7: the token handler use cases and the Telegram mini app exchange."""

import base64
import json

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import RoleMissingError, UnknownClientError
from app.shared.actor import Role
from app.shared.base_error import UnauthorizedError
from app.shared.contracts.identity import UserStatus
from tests.identity.support import World, sign_init_data

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="TelegramWebview")


def fake_jwt(claims: dict) -> str:
    """An unsigned token; the refresh use case only reads its payload."""
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{body}.sig"


async def test_exchange_code_returns_the_tokens_for_the_cookie_and_the_body(
    auth_world: World,
) -> None:
    """GEN-7: the refresh token is separate, so the handler can put it in a cookie."""
    grant = await auth_world.auth.exchange_code.execute(
        "sp", "code-1", "verifier-1", "https://sp.example/cb"
    )

    assert grant.access_token == "access.jwt.token"
    assert grant.refresh_token == "refresh-1"
    assert auth_world.hydra.last("exchange_code") == {
        "client_id": "sp",
        "code": "code-1",
        "verifier": "verifier-1",
        "redirect_uri": "https://sp.example/cb",
    }


async def test_token_handler_serves_only_our_web_clients(auth_world: World) -> None:
    """The cookie name comes from the client id, so unknown ids are refused."""
    with pytest.raises(UnknownClientError):
        await auth_world.auth.exchange_code.execute("evil", "c", "v", "https://x")


async def test_refresh_touches_the_session_named_in_the_new_token(
    auth_world: World,
) -> None:
    """ID-17: last activity is recorded from refreshes (at most once a minute)."""
    user = await auth_world.add_user()
    session = auth_world.add_session(user)
    auth_world.clock.advance(minutes=5)
    auth_world.hydra.tokens = auth_world.hydra.tokens.__class__(
        access_token=fake_jwt({"ext": {"sid": str(session.id)}}),
        expires_in=600,
        refresh_token="refresh-2",
    )

    grant = await auth_world.auth.refresh_tokens.execute("sp", "refresh-1")

    assert grant.refresh_token == "refresh-2"
    assert auth_world.store.sessions[session.id].last_seen_at == auth_world.clock.now()


async def test_refresh_with_a_bad_token_is_unauthorized(auth_world: World) -> None:
    """The handler turns this into a 401 and clears the cookie."""

    async def refuse(client_id: str, refresh_token: str):
        raise UnauthorizedError()

    auth_world.hydra.refresh = refuse  # type: ignore[method-assign]

    with pytest.raises(UnauthorizedError):
        await auth_world.auth.refresh_tokens.execute("sp", "stale")


async def test_logout_revokes_the_session_behind_the_refresh_token(
    auth_world: World,
) -> None:
    """UF-ID-11: logging out ends our session and the token at Hydra."""
    user = await auth_world.add_user()
    session = auth_world.add_session(user)
    auth_world.hydra.introspection = {"active": True, "ext": {"sid": str(session.id)}}

    url = await auth_world.auth.log_out_client.execute("sp", "refresh-1")

    assert url == "http://localhost:4444/oauth2/sessions/logout"
    assert auth_world.store.sessions[session.id].revoked_at is not None
    assert await auth_world.redis.exists(f"auth:revoked:{session.id}")
    assert auth_world.hydra.last("revoke_token")["token"] == "refresh-1"


async def test_logout_without_a_cookie_still_returns_the_url(
    auth_world: World,
) -> None:
    """No refresh token: nothing to revoke, the browser still ends Hydra's session."""
    url = await auth_world.auth.log_out_client.execute("sp", None)

    assert url.endswith("/oauth2/sessions/logout")
    assert "revoke_token" not in auth_world.hydra.names()


async def test_hydra_logout_challenge_closes_the_matching_session(
    auth_world: World,
) -> None:
    """The Session of the Hydra login session is revoked when logout is accepted."""
    user = await auth_world.add_user()
    session = auth_world.add_session(user, hydra_sid="sid-9")
    from app.modules.identity.ports.hydra_gateway import LogoutRequest

    auth_world.hydra.logout_requests["lo-1"] = LogoutRequest(
        "lo-1", str(user.id), "sid-9"
    )

    redirect = await auth_world.auth.accept_logout.execute("lo-1")

    assert redirect == "https://hydra/after-logout"
    assert auth_world.store.sessions[session.id].revoked_at is not None


async def test_telegram_exchange_signs_an_assertion_for_the_linked_user(
    auth_world: World,
) -> None:
    """ID-19: initData proves the Telegram account; Hydra gets our signed assertion."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)
    init_data = sign_init_data(auth_date=int(auth_world.clock.now().timestamp()))

    grant = await auth_world.auth.exchange_telegram_init_data.execute(
        "sp", init_data, CTX
    )

    assert grant.access_token == "tg.access.token"
    assert grant.refresh_token is None
    (session,) = auth_world.store.sessions.values()
    assert session.amr == ["tg"]
    call = auth_world.hydra.last("jwt_bearer")
    assert call["scope"] == "openid offline_access"
    assert call["audience"] == "ihsp-api"
    claims = auth_world.auth.signer.read(call["assertion"])
    assert claims is not None
    assert (claims.user_id, claims.session_id, claims.amr) == (
        user.id,
        session.id,
        ("tg",),
    )


async def test_telegram_exchange_accepts_init_data_up_to_12_hours_old(
    auth_world: World,
) -> None:
    """The mini app re-sends initData on 401 for one school day (12 h)."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)
    opened = int(auth_world.clock.now().timestamp())
    auth_world.clock.advance(hours=11)

    grant = await auth_world.auth.exchange_telegram_init_data.execute(
        "sp", sign_init_data(auth_date=opened), CTX
    )
    assert grant.access_token

    auth_world.clock.advance(hours=2)
    with pytest.raises(UnauthorizedError):
        await auth_world.auth.exchange_telegram_init_data.execute(
            "sp", sign_init_data(auth_date=opened), CTX
        )


async def test_telegram_exchange_for_an_unlinked_account_is_unauthorized(
    auth_world: World,
) -> None:
    """ID-19: only linked Telegram accounts get tokens."""
    init_data = sign_init_data(
        telegram_id=999, auth_date=int(auth_world.clock.now().timestamp())
    )

    with pytest.raises(UnauthorizedError):
        await auth_world.auth.exchange_telegram_init_data.execute("sp", init_data, CTX)


async def test_telegram_exchange_for_a_blocked_user_is_unauthorized(
    auth_world: World,
) -> None:
    """GEN-5: blocked users get nothing from the mini app either."""
    user = await auth_world.add_user(status=UserStatus.BLOCKED)
    auth_world.add_link(user, 555)

    with pytest.raises(UnauthorizedError):
        await auth_world.auth.exchange_telegram_init_data.execute(
            "sp", sign_init_data(auth_date=int(auth_world.clock.now().timestamp())), CTX
        )


async def test_staff_mini_app_needs_the_teacher_role(auth_world: World) -> None:
    """ID-16: the staff client requires the teacher role."""
    student = await auth_world.add_user()
    auth_world.add_link(student, 555)

    with pytest.raises(RoleMissingError):
        await auth_world.auth.exchange_telegram_init_data.execute(
            "staff",
            sign_init_data(auth_date=int(auth_world.clock.now().timestamp())),
            CTX,
        )

    teacher = await auth_world.add_user(roles={Role.TEACHER}, login="t.teacher")
    auth_world.store.links[555].user_id = teacher.id
    grant = await auth_world.auth.exchange_telegram_init_data.execute(
        "staff", sign_init_data(auth_date=int(auth_world.clock.now().timestamp())), CTX
    )
    assert grant.access_token


async def test_tampered_init_data_is_unauthorized(auth_world: World) -> None:
    """ID-20: a bad signature never reaches Hydra."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)
    good = sign_init_data(auth_date=int(auth_world.clock.now().timestamp()))

    with pytest.raises(UnauthorizedError):
        await auth_world.auth.exchange_telegram_init_data.execute(
            "sp", good.replace("aleksey", "mallory"), CTX
        )

    assert "jwt_bearer" not in auth_world.hydra.names()


async def test_repeated_telegram_exchanges_reuse_the_mini_app_session(
    auth_world: World,
) -> None:
    """Review 2026-10-11: initData replays do not pile up session rows."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)
    init_data = sign_init_data(auth_date=int(auth_world.clock.now().timestamp()))

    await auth_world.auth.exchange_telegram_init_data.execute("sp", init_data, CTX)
    auth_world.clock.advance(hours=1)
    await auth_world.auth.exchange_telegram_init_data.execute("sp", init_data, CTX)

    (session,) = auth_world.store.sessions.values()
    assert session.last_seen_at == auth_world.clock.now()


async def test_telegram_exchange_is_limited_per_telegram_user(
    auth_world: World,
) -> None:
    """Review 2026-10-11: about 30 exchanges per hour per Telegram account."""
    from app.shared.base_error import RateLimitedError

    user = await auth_world.add_user()
    auth_world.add_link(user, 555)
    init_data = sign_init_data(auth_date=int(auth_world.clock.now().timestamp()))
    await auth_world.redis.set("rl:tg-exchange:555", "30")
    await auth_world.redis.expire("rl:tg-exchange:555", 3600)

    with pytest.raises(RateLimitedError):
        await auth_world.auth.exchange_telegram_init_data.execute("sp", init_data, CTX)
