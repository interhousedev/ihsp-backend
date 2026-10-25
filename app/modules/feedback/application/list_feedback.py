"""All feedback for administrators: filters and a keyset cursor."""

from dataclasses import dataclass

from app.modules.feedback.application.cursors import decode_cursor, encode_cursor
from app.modules.feedback.application.views import FeedbackPresenter, FeedbackView
from app.modules.feedback.domain.feedback import (
    FeedbackArea,
    FeedbackKind,
    FeedbackStatus,
)
from app.modules.feedback.ports.feedback_repository import FeedbackFilter, PageAfter
from app.modules.feedback.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class FeedbackPage:
    """One page and the cursor of the next (None on the last page)."""

    items: list[FeedbackView]
    next_cursor: str | None


class ListFeedback:
    """Newest first, with the reporter of every item."""

    def __init__(
        self, *, uow_factory: UowFactory, presenter: FeedbackPresenter
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._presenter = presenter

    async def execute(
        self,
        *,
        status: FeedbackStatus | None = None,
        kind: FeedbackKind | None = None,
        area: FeedbackArea | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> FeedbackPage:
        """Return one page.

        Raises:
            FeedbackInvalidError: The cursor is broken.
        """
        after = decode_cursor(cursor)
        flt = FeedbackFilter(status=status, kind=kind, area=area)
        async with self._uow_factory() as uow:
            items = await uow.feedback.list_page(flt, after, limit + 1)
        more = len(items) > limit
        items = items[:limit]
        next_cursor = (
            encode_cursor(PageAfter(items[-1].created_at, items[-1].id))
            if more
            else None
        )
        views = await self._presenter.items(items, with_reporter=True)
        return FeedbackPage(items=views, next_cursor=next_cursor)
