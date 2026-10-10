"""GET /v1/admin/teachers."""

from typing import Annotated

from app.interfaces.http.v1.admin_users.photos import user_responses
from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep
from app.shared.contracts.identity import UserStatus
from app.shared.pagination import Page

from fastapi import Query


async def get_teachers(
    _admin: AdminDep,
    auth: AuthDep,
    query: str | None = None,
    status: UserStatus | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[AdminUserResponse]:
    """Teachers, newest first."""
    page = await auth.list_teachers.execute(
        query=query, status=status, cursor=cursor, limit=limit
    )
    items = await user_responses(auth, page.items)
    return Page[AdminUserResponse](items=items, next_cursor=page.next_cursor)
