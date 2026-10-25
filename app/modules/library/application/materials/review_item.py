"""A librarian decides about an item: approve, reject, hold, restore (LIB-13)."""

from uuid import UUID

from app.modules.library.application.detail import DetailBuilder, ItemDetailView
from app.modules.library.application.materials.decisions import Decision, Decisions
from app.modules.library.domain.access import can_view, is_librarian
from app.modules.library.domain.errors import ItemNotFoundError
from app.modules.library.domain.material_flow import (
    ReviewAction,
    check_reason,
    check_reviewer,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError


class ReviewItem:
    """One decision on one item; reasons are required except for approve (LIB-13)."""

    def __init__(
        self, *, uow_factory: UowFactory, decisions: Decisions, detail: DetailBuilder
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.decisions = decisions
        self.detail = detail

    async def execute(
        self,
        actor: Actor,
        item_id: UUID,
        action: ReviewAction,
        *,
        reason: str | None,
        note: str | None,
        locale: str,
    ) -> ItemDetailView:
        """Apply the decision and return the item as the librarian now sees it."""
        if not is_librarian(actor):
            raise ForbiddenError(params={"roles": ["librarian", "admin"]})
        reason = check_reason(action, reason)
        async with self.uow_factory() as uow:
            item = await uow.items.get(item_id, lock=True)
            if item is None or not can_view(item, actor):
                raise ItemNotFoundError()
            check_reviewer(
                action,
                owner_id=item.owner_id,
                reviewer_id=actor.user_id,
                reviewer_is_admin=Role.ADMIN in actor.roles,
            )
            await self.decisions.apply(
                uow,
                item,
                Decision(
                    action,
                    reason=reason,
                    note=(note or "").strip() or None,
                    actor_id=actor.user_id,
                    actor_is_admin=Role.ADMIN in actor.roles,
                ),
            )
            view = await self.detail.build(uow, item, viewer=actor, locale=locale)
            await uow.commit()
        return view
