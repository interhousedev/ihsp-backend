"""The student is told how the excuse stands."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class ExcuseDecidedRenderer(DescribedRenderer):
    """The student is told how the excuse stands."""

    notification_type = NotificationType.EXCUSE_DECIDED
