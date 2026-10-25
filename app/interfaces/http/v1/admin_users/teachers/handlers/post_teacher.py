"""POST /v1/admin/teachers: create a teacher account."""

from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.admin_users.teachers.schemas import (
    TeacherCreateBody,
    TeacherCreatedResponse,
)
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep, CtxDep


async def post_teacher(
    body: TeacherCreateBody, admin: AdminDep, auth: AuthDep, ctx: CtxDep
) -> TeacherCreatedResponse:
    """Generate the login, store the account as pending, return the link."""
    created = await auth.create_teacher.execute(
        admin.user_id,
        last_name=body.last_name,
        first_name=body.first_name,
        middle_name=body.middle_name,
        email=str(body.email),
        ctx=ctx,
    )
    return TeacherCreatedResponse(
        user=AdminUserResponse.of(created.user),
        activation_url=created.activation_url,
    )
