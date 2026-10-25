"""Telegram notice for librarians that an item was reported."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class LibraryReportFiledRenderer(DescribedRenderer):
    """Names the reported item and the reason; never the reporter."""

    notification_type = NotificationType.LIBRARY_REPORT_FILED
    link_button_key = "notify-btn-open-library-queue"
