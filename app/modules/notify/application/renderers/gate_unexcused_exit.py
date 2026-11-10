"""A student left the building in lesson time without an excuse (curator's alert)."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class GateUnexcusedExitRenderer(DescribedRenderer):
    """A student walked out during a lesson without an excuse."""

    notification_type = NotificationType.GATE_UNEXCUSED_EXIT
