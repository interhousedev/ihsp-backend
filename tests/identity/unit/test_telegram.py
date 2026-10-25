"""ID-18 to ID-21, ID-19, ID-20: linking Telegram through the mini app login page."""

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import (
    InvalidCredentialsError,
    OtpInvalidError,
    TelegramLinkedElsewhereError,
)
from app.shared.actor import Role
from app.shared.base_error import UnauthorizedError
from tests.identity.support import PASSWORD, World, sign_init_data

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="TelegramWebview")


def init_data(world: World, telegram_id: int = 555) -> str:
    """Fresh signed initData of a Telegram account."""
    return sign_init_data(
        telegram_id=telegram_id, auth_date=int(world.clock.now().timestamp())
    )


async def test_status_of_an_unlinked_account_is_false(auth_world: World) -> None:
    """UF-BOT-01: the page shows the login form."""
    result = await auth_world.auth.telegram_status.execute(init_data(auth_world))

    assert (result.linked, result.login) == (False, None)


async def test_status_of_a_linked_account_names_the_login(auth_world: World) -> None:
    """UF-BOT-01 5b: already linked."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)

    result = await auth_world.auth.telegram_status.execute(init_data(auth_world))

    assert (result.linked, result.login) == (True, user.login)


async def test_status_refuses_old_or_forged_init_data(auth_world: World) -> None:
    """UF-BOT-01 3b: expired or tampered data is rejected."""
    old = sign_init_data(auth_date=int(auth_world.clock.now().timestamp()) - 7200)

    with pytest.raises(UnauthorizedError):
        await auth_world.auth.telegram_status.execute(old)
    with pytest.raises(UnauthorizedError):
        await auth_world.auth.telegram_status.execute("hash=abc&auth_date=1")


async def test_password_login_links_the_telegram_account_and_announces_it(
    auth_world: World,
) -> None:
    """ID-19, ID-21: a new link emits telegram_linked and an email notice."""
    user = await auth_world.add_user()

    result = await auth_world.auth.telegram_login.execute(
        init_data(auth_world),
        user.login or "",
        password=PASSWORD,
        otp_code=None,
        ctx=CTX,
    )

    assert (result.linked, result.login) == (True, user.login)
    link = auth_world.store.links[555]
    assert (link.user_id, link.otp_delivery, link.username) == (
        user.id,
        True,
        "aleksey",
    )
    assert auth_world.store.notification_types() == ["telegram_linked"]
    payload = auth_world.store.notifications[0].payload
    assert payload == {"telegram_username": "aleksey", "telegram_user_id": 555}
    assert "telegram.linked" in auth_world.store.audit_types(user.id)
    (notice,) = auth_world.email.to(user.recovery_email or "", "notice")
    assert notice["text_key"] == "id-mail-notice-telegram-linked"


async def test_linking_an_account_owned_by_another_user_is_a_conflict(
    auth_world: World,
) -> None:
    """ID-18, UF-BOT-01 5a: one Telegram account, one IHSP account."""
    owner = await auth_world.add_user()
    auth_world.add_link(owner, 555)
    other = await auth_world.add_user(
        login="other.user", recovery_email="o@example.org"
    )

    with pytest.raises(TelegramLinkedElsewhereError) as caught:
        await auth_world.auth.telegram_login.execute(
            init_data(auth_world),
            other.login or "",
            password=PASSWORD,
            otp_code=None,
            ctx=CTX,
        )

    assert caught.value.status == 409
    assert auth_world.store.links[555].user_id == owner.id


async def test_relogin_with_an_already_linked_account_is_just_confirmed(
    auth_world: World,
) -> None:
    """UF-BOT-01 5b: no second notification."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)

    result = await auth_world.auth.telegram_login.execute(
        init_data(auth_world),
        user.login or "",
        password=PASSWORD,
        otp_code=None,
        ctx=CTX,
    )

    assert result.linked is True
    assert auth_world.store.notifications == []


async def test_wrong_password_does_not_link(auth_world: World) -> None:
    """ID-19: no password, no link."""
    user = await auth_world.add_user()

    with pytest.raises(InvalidCredentialsError):
        await auth_world.auth.telegram_login.execute(
            init_data(auth_world),
            user.login or "",
            password="Wr0ngPassword",
            otp_code=None,
            ctx=CTX,
        )

    assert auth_world.store.links == {}


async def test_administration_needs_a_code_after_the_password(
    auth_world: World,
) -> None:
    """ID-11: admins additionally need otp_code; the first call sends it."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)

    first = await auth_world.auth.telegram_login.execute(
        init_data(auth_world),
        admin.login or "",
        password=PASSWORD,
        otp_code=None,
        ctx=CTX,
    )

    assert first.linked is False
    assert first.second_factor_result is not None
    assert first.second_factor_result.second_factor is not None
    code = auth_world.otp.last("tg-login").code

    second = await auth_world.auth.telegram_login.execute(
        init_data(auth_world),
        admin.login or "",
        password=PASSWORD,
        otp_code=code,
        ctx=CTX,
    )
    assert second.linked is True
    assert 555 in auth_world.store.links


async def test_mini_app_otp_request_then_passwordless_login_links_the_account(
    auth_world: World,
) -> None:
    """The mini app has no Hydra challenge: initData proves the caller instead."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)

    await auth_world.auth.request_telegram_otp.execute(
        init_data(auth_world), user.login or "", CTX
    )
    code = auth_world.otp.last("login").code
    result = await auth_world.auth.telegram_login.execute(
        init_data(auth_world), user.login or "", password=None, otp_code=code, ctx=CTX
    )

    assert (result.linked, result.login) == (True, user.login)
    assert auth_world.store.links[555].user_id == user.id


async def test_mini_app_otp_request_rejects_forged_init_data(auth_world: World) -> None:
    """ID-20: without verified initData no code is sent."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)

    with pytest.raises(UnauthorizedError):
        await auth_world.auth.request_telegram_otp.execute(
            "hash=bad&auth_date=1", user.login or "", CTX
        )

    assert auth_world.otp.codes == []


async def test_mini_app_wrong_otp_code_does_not_link(auth_world: World) -> None:
    """ID-14: a wrong code is refused with the attempts left."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)
    await auth_world.auth.request_telegram_otp.execute(
        init_data(auth_world), user.login or "", CTX
    )
    good = auth_world.otp.last().code

    with pytest.raises(OtpInvalidError):
        await auth_world.auth.telegram_login.execute(
            init_data(auth_world),
            user.login or "",
            password=None,
            otp_code="000000" if good != "000000" else "111111",
            ctx=CTX,
        )

    assert auth_world.store.links == {}


async def test_login_without_password_or_code_is_refused(auth_world: World) -> None:
    """The page must send one of the two."""
    user = await auth_world.add_user()

    with pytest.raises(InvalidCredentialsError):
        await auth_world.auth.telegram_login.execute(
            init_data(auth_world),
            user.login or "",
            password=None,
            otp_code=None,
            ctx=CTX,
        )


async def test_a_broken_mail_relay_does_not_undo_the_link(auth_world: World) -> None:
    """ID-21: the notice email is best effort."""
    user = await auth_world.add_user()
    auth_world.email.fail = True

    result = await auth_world.auth.telegram_login.execute(
        init_data(auth_world),
        user.login or "",
        password=PASSWORD,
        otp_code=None,
        ctx=CTX,
    )

    assert result.linked is True
    assert 555 in auth_world.store.links
