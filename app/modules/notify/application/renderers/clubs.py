"""Club and event notices of the activities module."""

from typing import Any
from uuid import UUID

from app.modules.notify.application.describe import Description
from app.modules.notify.application.renderers.described import (
    Buttons,
    DescribedRenderer,
)
from app.settings import UrlsSettings
from app.shared.base_error import BaseError
from app.shared.contracts.callbacks import ClubTransferCb
from app.shared.contracts.files import FilesApi
from app.shared.contracts.notify import PhotoRef, RenderContext, RenderedMessage
from app.shared.i18n.core import I18nCore
from app.shared.ids import uuid_to_b64
from app.shared.notifications import NotificationType

import structlog

log = structlog.get_logger(__name__)

MAX_PHOTOS = 10


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
    """Club announcement; photos (payload ``photo_file_ids``) ride along."""

    notification_type = NotificationType.CLUB_ANNOUNCEMENT
    link_button_key = "notify-btn-open-clubs"

    def __init__(self, i18n: I18nCore, urls: UrlsSettings, files: FilesApi) -> None:
        """Store translations, the app URLs and the files API."""
        super().__init__(i18n, urls)
        self.files = files

    async def __call__(
        self, payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage | None:
        """Render the text and attach the readable photos (at most ten)."""
        message = await super().__call__(payload, ctx)
        if message is None:
            return None
        photos = await self._photos(payload.get("photo_file_ids") or [])
        if not photos:
            return message
        return RenderedMessage(
            text_html=message.text_html, buttons=message.buttons, photos=photos
        )

    async def _photos(self, file_ids: list[Any]) -> tuple[PhotoRef, ...]:
        """Read the photos in order; an unreadable or missing one is skipped."""
        photos: list[PhotoRef] = []
        for raw_id in file_ids[:MAX_PHOTOS]:
            try:
                file_id = UUID(str(raw_id))
                ref = await self.files.get(file_id)
                if ref is None:
                    log.warning("announcement_photo_missing", file_id=str(file_id))
                    continue
                data = await self.files.read_bytes(file_id)
            except (BaseError, ValueError):
                log.warning("announcement_photo_unreadable", file_id=str(raw_id))
                continue
            photos.append(PhotoRef(name=ref.name, data=data, cache_key=str(file_id)))
        return tuple(photos)


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
