"""GET /v1/admin/feedback."""

from typing import Annotated

from app.interfaces.http.v1.admin_feedback.deps import AdminActor, ContainerDep
from app.interfaces.http.v1.feedback.schemas import (
    AdminFeedbackListItem,
    AdminFeedbackListOut,
    FeedbackAreaValue,
    FeedbackKindValue,
    FeedbackStatusValue,
)
from app.modules.feedback.domain.feedback import (
    FeedbackArea,
    FeedbackKind,
    FeedbackStatus,
)

from fastapi import Query


async def list_feedback(
    container: ContainerDep,
    actor: AdminActor,
    status: Annotated[FeedbackStatusValue | None, Query()] = None,
    kind: Annotated[FeedbackKindValue | None, Query()] = None,
    area: Annotated[FeedbackAreaValue | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminFeedbackListOut:
    """All feedback, newest first; ``next_cursor`` is None on the last page."""
    page = await container.feedback.list_all.execute(
        status=FeedbackStatus(status) if status else None,
        kind=FeedbackKind(kind) if kind else None,
        area=FeedbackArea(area) if area else None,
        cursor=cursor,
        limit=limit,
    )
    return AdminFeedbackListOut(
        items=[AdminFeedbackListItem.of(view) for view in page.items],
        next_cursor=page.next_cursor,
    )
