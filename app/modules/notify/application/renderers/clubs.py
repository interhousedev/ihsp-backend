"""Club and event notices of the activities module."""

from typing import Any
from uuid import UUID

from app.modules.notify.application.describe import Description
from app.modules.notify.application.renderers.described import (
    Buttons,
    DescribedRenderer,
)
from app.shared.contracts.callbacks import ClubTransferCb
from app.shared.contracts.notify import RenderContext
from app.shared.ids import uuid_to_b64
from app.shared.notifications import NotificationType


class EventReminderRenderer(DescribedRenderer):
    """Club or event notice; the button opens the events page."""

    notification_type = NotificationType.EVENT_REMINDER
    link_button_key = "notify-btn-open-events"


class EventChangedRenderer(DescribedRenderer):
    """Club or event notice; the button opens the events page."""

    notification_type = NotificationType.EVENT_CHANGED
    link_button_key = "notify-btn-open-events"


class EventCancelledRenderer(DescribedRenderer):
    """Club or event notice; the button opens the events page."""

    notification_type = NotificationType.EVENT_CANCELLED
    link_button_key = "notify-btn-open-events"


class EventRatingRequestRenderer(DescribedRenderer):
    """Club or event notice; the button opens the events page."""

    notification_type = NotificationType.EVENT_RATING_REQUEST
    link_button_key = "notify-btn-open-events"


class ClubAnnouncementRenderer(DescribedRenderer):
    """Club or event notice; the button opens the clubs page."""

    notification_type = NotificationType.CLUB_ANNOUNCEMENT
    link_button_key = "notify-btn-open-clubs"


class ClubJoinRequestRenderer(DescribedRenderer):
    """Club or event notice; the button opens the clubs page."""

    notification_type = NotificationType.CLUB_JOIN_REQUEST
    link_button_key = "notify-btn-open-clubs"


class ClubJoinResultRenderer(DescribedRenderer):
    """Club or event notice; the button opens the clubs page."""

    notification_type = NotificationType.CLUB_JOIN_RESULT
    link_button_key = "notify-btn-open-clubs"


class ClubTransferOfferRenderer(DescribedRenderer):
    """An ownership offer with Accept and Decline buttons; answers get a link."""

    notification_type = NotificationType.CLUB_TRANSFER_OFFER
    link_button_key = "notify-btn-open-clubs"

    def buttons(
        self, payload: dict[str, Any], ctx: RenderContext, description: Description
    ) -> Buttons | None:
        """Accept and decline for an offer; only the link for an answer."""
        rows: Buttons = super().buttons(payload, ctx, description) or []
        transfer = str(payload.get("transfer_id", ""))
        if payload.get("result") or not transfer:
            return rows
        t = self.i18n.get_context(ctx.locale)
        packed = uuid_to_b64(UUID(transfer))
        return [
            [
                {
                    "text": t("notify-btn-transfer-accept"),
                    "callback_data": ClubTransferCb(t=packed, d="a").pack(),
                },
                {
                    "text": t("notify-btn-transfer-decline"),
                    "callback_data": ClubTransferCb(t=packed, d="d").pack(),
                },
            ],
            *rows,
        ]


class DraftInviteRenderer(DescribedRenderer):
    """Club or event notice; the button opens the clubs page."""

    notification_type = NotificationType.DRAFT_INVITE
    link_button_key = "notify-btn-open-clubs"


class PositionApplicationResultRenderer(DescribedRenderer):
    """Club or event notice; the button opens the clubs page."""

    notification_type = NotificationType.POSITION_APPLICATION_RESULT
    link_button_key = "notify-btn-open-clubs"


class ClubOwnerGraduatingRenderer(DescribedRenderer):
    """Club or event notice; the button opens the clubs page."""

    notification_type = NotificationType.CLUB_OWNER_GRADUATING
    link_button_key = "notify-btn-open-clubs"
