"""ID-21, BOT-10: codes go to Telegram and email without blocking each other."""

from app.modules.identity.infrastructure.otp_sender import ChannelOtpSender
from app.modules.identity.ports.otp_sender import OtpContext
from app.shared.i18n.core import I18nCore
from tests.identity.support import World


def build(world: World, i18n: I18nCore, *, telegram: bool = True) -> ChannelOtpSender:
    """The real sender over the world's fakes."""
    return ChannelOtpSender(
        uow_factory=world.auth.uow_factory,
        email=world.email,
        telegram=world.telegram if telegram else None,
        i18n=i18n,
        redis=world.redis,
        clock=world.clock,
        id_app_url="https://id.example",
        app_name="IHSP",
    )


async def test_code_goes_to_every_telegram_account_with_delivery_on(
    auth_world: World, i18n: I18nCore
) -> None:
    """ID-21: accounts with delivery off or blocked are skipped."""
    user = await auth_world.add_user(otp_enabled=True)
    auth_world.add_link(user, 1)
    auth_world.add_link(user, 2, otp_delivery=False)
    auth_world.add_link(user, 3, blocked_at=auth_world.clock.now())

    await build(auth_world, i18n).send_code(
        user.to_ref(),
        "123456",
        purpose="login",
        channels=["telegram"],
        context=OtpContext(ip="203.0.113.5", user_agent="Firefox"),
    )

    assert [chat for chat, _, _ in auth_world.telegram.messages] == [1]
    _, text, buttons = auth_world.telegram.messages[0]
    assert "<code>123456</code>" in text
    assert "203.0.113.5" in text and "Firefox" in text
    assert buttons == [[{"text": "Это не я", "url": "https://id.example/security/"}]]


async def test_telegram_messages_are_queued_for_deletion_after_five_minutes(
    auth_world: World, i18n: I18nCore
) -> None:
    """UF-BOT-02: the scheduler removes OTP messages after 5 minutes."""
    user = await auth_world.add_user(otp_enabled=True)
    auth_world.add_link(user, 1)

    await build(auth_world, i18n).send_code(
        user.to_ref(), "123456", purpose="login", channels=["telegram"]
    )

    queued = await auth_world.redis.zrange("tg:otp-msgs", 0, -1, withscores=True)
    assert len(queued) == 1
    member, score = queued[0]
    assert member.startswith("1:")
    assert score == auth_world.clock.now().timestamp() + 300


async def test_code_goes_to_the_verified_recovery_email(
    auth_world: World, i18n: I18nCore
) -> None:
    """ID-22: email is a channel when chosen."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)

    await build(auth_world, i18n).send_code(
        user.to_ref(), "654321", purpose="login", channels=["email"]
    )

    assert auth_world.email.last_code(user.recovery_email or "") == "654321"


async def test_a_dead_telegram_chat_does_not_block_the_email(
    auth_world: World, i18n: I18nCore
) -> None:
    """A failing channel is logged and the others still deliver."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)
    auth_world.add_link(user, 1)
    auth_world.telegram.failing.add(1)

    await build(auth_world, i18n).send_code(
        user.to_ref(), "111111", purpose="login", channels=["telegram", "email"]
    )

    assert auth_world.telegram.messages == []
    assert auth_world.email.last_code(user.recovery_email or "") == "111111"


async def test_without_a_telegram_sender_only_email_is_used(
    auth_world: World, i18n: I18nCore
) -> None:
    """Before the bot sender is wired the telegram channel is skipped."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)
    auth_world.add_link(user, 1)

    await build(auth_world, i18n, telegram=False).send_code(
        user.to_ref(), "222222", purpose="login", channels=["telegram", "email"]
    )

    assert auth_world.email.last_code(user.recovery_email or "") == "222222"
