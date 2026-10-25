"""GET /v1/staff/lms/creators: the people who may create courses."""

from typing import Annotated

from app.interfaces.http.v1.id.dependencies import ActorDep, AuthDep
from app.interfaces.http.v1.lms_authoring.creators.schemas import (
    CourseCreatorResponse,
)
from app.shared.pagination import Page

from fastapi import Query


async def list_creators(
    actor: ActorDep,
    auth: AuthDep,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[CourseCreatorResponse]:
    """Holders of `lms_creator`, newest first (LMS admins only)."""
    page = await auth.manage_course_creators.list(actor, cursor=cursor, limit=limit)
    items = [CourseCreatorResponse.of(user) for user in page.items]
    return Page[CourseCreatorResponse](items=items, next_cursor=page.next_cursor)
