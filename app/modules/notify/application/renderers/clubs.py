"""Club and event notices of the activities module."""

from app.modules.notify.application.renderers.described import DescribedRenderer
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
    """Club or event notice; the button opens the clubs page."""

    notification_type = NotificationType.CLUB_TRANSFER_OFFER
    link_button_key = "notify-btn-open-clubs"


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
