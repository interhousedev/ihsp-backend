"""GET /v1/admin/users: search users."""

from typing import Annotated

from app.interfaces.http.v1.admin_users.photos import user_responses
from app.interfaces.http.v1.admin_users.schemas import AdminUserResponse
from app.interfaces.http.v1.id.dependencies import AdminDep, AuthDep
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.pagination import Page

from fastapi import Query


async def get_users(
    _admin: AdminDep,
    auth: AuthDep,
    query: str | None = None,
    role: Role | None = None,
    status: UserStatus | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[AdminUserResponse]:
    """Newest first."""
    page = await auth.list_users.execute(
        query=query, role=role, status=status, cursor=cursor, limit=limit
    )
    items = await user_responses(auth, page.items)
    return Page[AdminUserResponse](items=items, next_cursor=page.next_cursor)
