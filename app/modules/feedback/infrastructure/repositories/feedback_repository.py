"""SQL repository of feedback items and responses."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.feedback.domain.feedback import (
    Delivery,
    DeliveryStatus,
    Feedback,
    FeedbackArea,
    FeedbackKind,
    FeedbackResponse,
    FeedbackSource,
    FeedbackStatus,
    ResponseChannel,
)
from app.modules.feedback.infrastructure.orm.feedback_item import (
    FeedbackItemRow as Item,
)
from app.modules.feedback.infrastructure.orm.feedback_response import (
    FeedbackResponseRow as Answer,
)
from app.modules.feedback.ports.feedback_repository import FeedbackFilter, PageAfter

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

RESPONSE_COUNT = (
    select(func.count(Answer.id))
    .where(Answer.feedback_id == Item.id)
    .correlate(Item)
    .scalar_subquery()
)


def to_item(row: Item, response_count: int) -> Feedback:
    """Map a row to the domain item."""
    return Feedback(
        id=row.id,
        reporter_id=row.reporter_id,
        kind=FeedbackKind(row.kind),
        area=FeedbackArea(row.area),
        title=row.title,
        description=row.description,
        status=FeedbackStatus(row.status),
        source=FeedbackSource(row.source),
        created_at=row.created_at,
        updated_at=row.updated_at,
        page_url=row.page_url,
        attachment_file_ids=list(row.attachment_file_ids or []),
        response_count=int(response_count),
    )


def to_response(row: Answer) -> FeedbackResponse:
    """Map a row to the domain response."""
    return FeedbackResponse(
        id=row.id,
        feedback_id=row.feedback_id,
        author_id=row.author_id,
        text=row.text,
        channels=[ResponseChannel(c) for c in row.channels or []],
        deliveries=[
            Delivery(ResponseChannel(d["channel"]), DeliveryStatus(d["status"]))
            for d in row.deliveries or []
        ],
        created_at=row.created_at,
        attachment_file_ids=list(row.attachment_file_ids or []),
    )


def _filtered(
    query: Select[Any], flt: FeedbackFilter, after: PageAfter | None
) -> Select[Any]:
    if flt.status is not None:
        query = query.where(Item.status == flt.status.value)
    if flt.kind is not None:
        query = query.where(Item.kind == flt.kind.value)
    if flt.area is not None:
        query = query.where(Item.area == flt.area.value)
    if after is not None:
        query = query.where(
            or_(
                Item.created_at < after.created_at,
                and_(Item.created_at == after.created_at, Item.id < after.id),
            )
        )
    return query


class SqlFeedbackRepository:
    """Rows of `feedback.items` and `feedback.responses`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def add(self, item: Feedback) -> None:
        """Insert an item."""
        self.session.add(
            Item(
                id=item.id,
                reporter_id=item.reporter_id,
                kind=item.kind.value,
                area=item.area.value,
                title=item.title,
                description=item.description,
                status=item.status.value,
                source=item.source.value,
                page_url=item.page_url,
                attachment_file_ids=list(item.attachment_file_ids),
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )
        await self.session.flush()

    async def get(self, feedback_id: UUID) -> Feedback | None:
        """Return the item or None."""
        found = (
            await self.session.execute(
                select(Item, RESPONSE_COUNT).where(Item.id == feedback_id)
            )
        ).first()
        return None if found is None else to_item(found[0], found[1])

    async def set_status(
        self, feedback_id: UUID, status: FeedbackStatus, now: datetime
    ) -> None:
        """Change the status."""
        await self.session.execute(
            update(Item)
            .where(Item.id == feedback_id)
            .values(status=status.value, updated_at=now)
        )

    async def list_for_reporter(self, reporter_id: UUID) -> list[Feedback]:
        """The reporter's items, newest first."""
        rows = await self.session.execute(
            select(Item, RESPONSE_COUNT)
            .where(Item.reporter_id == reporter_id)
            .order_by(Item.created_at.desc(), Item.id.desc())
        )
        return [to_item(row, count) for row, count in rows.all()]

    async def list_page(
        self, flt: FeedbackFilter, after: PageAfter | None, limit: int
    ) -> list[Feedback]:
        """Items matching the filter, newest first, after the position."""
        query = _filtered(select(Item, RESPONSE_COUNT), flt, after)
        rows = await self.session.execute(
            query.order_by(Item.created_at.desc(), Item.id.desc()).limit(limit)
        )
        return [to_item(row, count) for row, count in rows.all()]

    async def add_response(self, response: FeedbackResponse) -> None:
        """Insert a response."""
        self.session.add(
            Answer(
                id=response.id,
                feedback_id=response.feedback_id,
                author_id=response.author_id,
                text=response.text,
                channels=[c.value for c in response.channels],
                deliveries=[
                    {"channel": d.channel.value, "status": d.status.value}
                    for d in response.deliveries
                ],
                attachment_file_ids=list(response.attachment_file_ids),
                created_at=response.created_at,
                updated_at=response.created_at,
            )
        )
        await self.session.flush()

    async def responses(self, feedback_id: UUID) -> list[FeedbackResponse]:
        """Responses of an item, oldest first."""
        rows = await self.session.scalars(
            select(Answer)
            .where(Answer.feedback_id == feedback_id)
            .order_by(Answer.created_at, Answer.id)
        )
        return [to_response(row) for row in rows]
