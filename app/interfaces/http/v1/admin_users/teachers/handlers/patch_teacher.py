"""PATCH /v1/admin/teachers/{id}."""

from uuid import UUID

from app.interfaces.http.v1.admin_users.photos import user_response
from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.admin_users.teachers.schemas import TeacherPatchBody
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def patch_teacher(
    id: UUID, body: TeacherPatchBody, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> AdminUserResponse:
    """Edit names; the email only until activation."""
    user = await auth.update_teacher.execute(
        admin,
        id,
        last_name=body.last_name,
        first_name=body.first_name,
        middle_name=body.middle_name,
        email=str(body.email) if body.email else None,
        ctx=ctx,
    )
    return await user_response(auth, user)
