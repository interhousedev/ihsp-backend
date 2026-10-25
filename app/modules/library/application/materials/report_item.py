"""Report an item to the librarians (LIB-14)."""

from datetime import timedelta
from uuid import UUID

from app.modules.library.application.materials.decisions import Decision, Decisions
from app.modules.library.application.materials.notices import report_filed_notices
from app.modules.library.domain.access import can_view, is_owner
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    ItemKind,
    ItemStatus,
    ReportReason,
    StatusReasonCode,
)
from app.modules.library.domain.errors import (
    InvalidTransitionError,
    ItemNotFoundError,
    LibraryRateLimitedError,
)
from app.modules.library.domain.material_flow import ReviewAction, uploader_role_of
from app.modules.library.domain.moderation_entities import Report
from app.modules.library.domain.moderation_rules import (
    UploadWindow,
    should_auto_hold,
    window_resets_at,
)
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.settings import LibrarySettings
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError, ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.ids import new_id

TEXT_MAX = 500
HELD_BY_REPORTS = StatusReasonCode.REPORTED.value
DAY = timedelta(days=1)


class ReportItem:
    """Store a report; enough reports hold the item until a librarian decides."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        identity: IdentityDirectory,
        decisions: Decisions,
        settings: LibrarySettings,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.identity = identity
        self.decisions = decisions
        self.settings = settings

    async def execute(
        self, actor: Actor, item_id: UUID, reason: ReportReason, text: str | None
    ) -> None:
        """File the report; a repeat of an open report is a no-op."""
        text = (text or "").strip() or None
        if text is not None and len(text) > TEXT_MAX:
            raise ValidationFailedError(params={"field": "text"})
        async with self.uow_factory() as uow:
            item = await uow.items.get(item_id, lock=True)
            self._check(item, actor)
            assert item is not None
            if await uow.moderation.has_open_report(item.id, actor.user_id, reason):
                return
            await self._check_limit(uow, actor)
            await uow.moderation.add_report(
                Report(
                    id=new_id(),
                    item_id=item.id,
                    reporter_id=actor.user_id,
                    reporter_role=uploader_role_of(actor.roles),
                    reason=reason,
                    created_at=self.clock.now(),
                    text=text,
                )
            )
            await self._after_report(uow, item, actor, reason)
            await uow.commit()

    @staticmethod
    def _check(item: Item | None, actor: Actor) -> None:
        if item is None or not can_view(item, actor):
            raise ItemNotFoundError()
        if is_owner(item, actor):
            raise ForbiddenError(support_details="reporting one's own item")
        if item.status is not ItemStatus.PUBLISHED:
            raise InvalidTransitionError(
                params={"status": item.status.value, "action": "report"}
            )

    async def _check_limit(self, uow: LibraryUnitOfWork, actor: Actor) -> None:
        """At most `limit_reports_day` reports in any 24 hours."""
        window = UploadWindow("day", DAY, self.settings.limit_reports_day)
        times = await uow.moderation.report_times(actor.user_id, self.clock.now() - DAY)
        resets_at = window_resets_at(window, times)
        if resets_at is not None:
            raise LibraryRateLimitedError(
                params={
                    "action": "report",
                    "limit": window.limit,
                    "resets_at": resets_at.isoformat(),
                }
            )

    async def _after_report(
        self, uow: LibraryUnitOfWork, item: Item, actor: Actor, reason: ReportReason
    ) -> None:
        """Count the open reports and hold the item when the rule says so."""
        open_reports = await uow.moderation.open_reports(item.id)
        item.open_reports = len(open_reports)
        hold = item.kind is not ItemKind.EXTERNAL and should_auto_hold(
            [report.signal for report in open_reports],
            threshold=self.settings.auto_hold_reporters,
        )
        if not hold:
            await uow.items.save(item)
            return
        seq = await self.decisions.apply(
            uow, item, Decision(ReviewAction.HOLD, reason=HELD_BY_REPORTS)
        )
        librarians = await self.identity.user_ids_with_roles(
            [Role.LIBRARIAN, Role.ADMIN]
        )
        uow.notify(
            *report_filed_notices(
                item, reason, [u for u in librarians if u != actor.user_id], seq
            )
        )
