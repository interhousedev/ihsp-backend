"""PATCH /v1/id/me/telegram/{telegram_user_id}: OTP delivery on or off."""

from app.interfaces.http.v1.id.account.schemas import TelegramPatchBody
from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep
from app.interfaces.http.v1.id.schemas import TelegramAccountResponse


async def patch_telegram(
    telegram_user_id: int, body: TelegramPatchBody, actor: ActorDep, auth: AuthDep
) -> TelegramAccountResponse:
    """Switch OTP delivery for one account."""
    link = await auth.update_telegram_account.execute(
        actor, telegram_user_id, otp_delivery=body.otp_delivery
    )
    return TelegramAccountResponse.of(link)
