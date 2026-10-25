"""POST /v1/admin/users/{id}/reset-otp."""

from uuid import UUID

from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep

from fastapi import Response


async def post_reset_otp(
    id: UUID, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> Response:
    """Unlink the user's Telegram accounts."""
    await auth.admin_reset_otp.execute(admin, id, ctx)
    return Response(status_code=204)
