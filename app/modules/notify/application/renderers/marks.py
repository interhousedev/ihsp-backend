"""New marks message with Open grades and Notification settings buttons (UF-BOT-04)."""

from typing import Any

from app.modules.notify.application.describe import Description
from app.modules.notify.application.renderers.described import (
    Buttons,
    DescribedRenderer,
    link_button,
)
from app.shared.contracts.callbacks import MenuCb
from app.shared.contracts.notify import RenderContext
from app.shared.notifications import NotificationType


class MarksRenderer(DescribedRenderer):
    """New marks and changed semester marks of one sync run."""

    notification_type = NotificationType.MARKS

    def buttons(
        self, payload: dict[str, Any], ctx: RenderContext, description: Description
    ) -> Buttons | None:
        """Open the grades page and the bot's settings screen."""
        t = self.i18n.get_context(ctx.locale)
        row: list[dict[str, Any]] = []
        if description.link is not None:
            row.append(
                link_button(t("notify-btn-open-grades"), description.link, self.urls)
            )
        row.append(
            {
                "text": t("notify-btn-notification-settings"),
                "callback_data": MenuCb(screen="settings").pack(),
            }
        )
        return [row]
