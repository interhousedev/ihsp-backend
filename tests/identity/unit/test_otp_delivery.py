from typing import Any

"""Codes that never reach the user: retry, email fallback, discard and resend."""

from app.modules.identity.application.otp_service import (
    OtpService,
    channels_with_email_fallback,
)
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import OtpDeliveryFailedError
from app.modules.identity.domain.user import User
from app.modules.identity.infrastructure.otp_sender import ChannelOtpSender
from app.shared.i18n.core import I18nCore
from tests.identity.support import World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


def service(world: World, i18n: I18nCore) -> OtpService:
    """The real service over the real sender (no retry delay) and the world's fakes."""
    sender = ChannelOtpSender(
        uow_factory=world.auth.uow_factory,
        email=world.email,
        telegram=world.telegram,
        i18n=i18n,
        redis=world.redis,
        clock=world.clock,
        id_app_url="https://id.example",
        retry_delay=0,
    )
    return OtpService(
        otp_store=world.auth.otp_store, otp_sender=sender, email=world.email
    )


async def send_step_up(otp: OtpService, user: User, world: World) -> list[str]:
    """What POST /v1/id/me/step-up does."""
    async with world.uow() as uow:
        links = await uow.telegram_links.list_for_user(user.id)
    return await otp.send(
        user,
        links,
        purpose="step-up",
        subject_key=str(user.id),
        ctx=CTX,
        channels=channels_with_email_fallback(user, links),
    )


async def test_a_transient_telegram_failure_is_retried_once(
    auth_world: World, i18n: I18nCore
) -> None:
    """A dropped connection on the first attempt still delivers on Telegram."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 1)
    calls = 0
    real = auth_world.telegram.send_message

    async def flaky(
        chat_id: int, text: str, buttons: list[list[dict[str, Any]]] | None = None
    ) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionResetError("Connection reset by peer")
        return await real(chat_id, text, buttons)

    auth_world.telegram.send_message = flaky  # type: ignore[method-assign]

    channels = await send_step_up(service(auth_world, i18n), user, auth_world)

    assert channels == ["telegram"]
    assert calls == 2
    assert len(auth_world.telegram.messages) == 1
    assert auth_world.email.sent == []


async def test_failed_telegram_falls_back_to_the_recovery_email(
    auth_world: World, i18n: I18nCore
) -> None:
    """Telegram down for both attempts: the verified email gets the same code."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 1)
    auth_world.telegram.failing.add(1)

    channels = await send_step_up(service(auth_world, i18n), user, auth_world)

    assert channels == ["email"]
    code = auth_world.email.last_code(user.recovery_email or "")
    assert await auth_world.auth.otp_store.verify("step-up", str(user.id), code)


async def test_no_delivery_raises_and_allows_an_immediate_resend(
    auth_world: World, i18n: I18nCore
) -> None:
    """Everything failed: 503 error, code and cooldown dropped, resend works."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 1)
    auth_world.telegram.failing.add(1)
    auth_world.email.fail = True
    otp = service(auth_world, i18n)

    with pytest.raises(OtpDeliveryFailedError) as caught:
        await send_step_up(otp, user, auth_world)

    assert caught.value.status == 503
    assert caught.value.code == "id/otp-delivery-failed"
    assert await auth_world.auth.otp_store.attempts_left("step-up", str(user.id)) == 0

    auth_world.telegram.failing.clear()
    channels = await send_step_up(otp, user, auth_world)  # no RateLimitedError

    assert channels == ["telegram"]
