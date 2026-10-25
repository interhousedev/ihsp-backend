"""GET /v1/admin/users/{id}: one account with sessions, Telegram and audit."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.schemas import AdminUserDetailResponse
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def get_user(
    id: UUID, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> AdminUserDetailResponse:
    """Opening a student profile is audited."""
    detail = await auth.get_user_detail.execute(admin, id, ctx)
    photo_url = await auth.photo_urls.url(detail.user.photo_file_id)
    return AdminUserDetailResponse.detail(detail, photo_url)
