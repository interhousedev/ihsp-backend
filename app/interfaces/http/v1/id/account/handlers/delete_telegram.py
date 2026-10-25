"""DELETE /v1/id/me/telegram/{telegram_user_id}: unlink an account."""

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep, CtxDep

from fastapi import Response


async def delete_telegram(
    telegram_user_id: int, actor: ActorDep, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Unlink (and so log out of the bot)."""
    await auth.unlink_telegram_account.execute(actor, telegram_user_id, ctx)
    return Response(status_code=204)
