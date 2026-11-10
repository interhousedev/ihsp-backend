"""A request to excuse a student, with approve and reject buttons."""

from typing import Any

from app.modules.notify.application.describe import Description
from app.modules.notify.application.renderers.described import (
    Buttons,
    DescribedRenderer,
    link_button,
)
from app.shared.contracts.callbacks import ExcuseCb
from app.shared.contracts.notify import RenderContext
from app.shared.notifications import NotificationType


class ExcuseRequestedRenderer(DescribedRenderer):
    """Each button carries a single-use decision token."""

    notification_type = NotificationType.EXCUSE_REQUESTED

    def buttons(
        self, payload: dict[str, Any], ctx: RenderContext, description: Description
    ) -> Buttons | None:
        """Approve, reject, and a link to the request."""
        t = self.i18n.get_context(ctx.locale)
        rows: Buttons = []
        approve = str(payload.get("approve_token", ""))
        reject = str(payload.get("reject_token", ""))
        if approve and reject:
            rows.append(
                [
                    {
                        "text": t("excuse-btn-approve"),
                        "callback_data": ExcuseCb(t=approve, d="a").pack(),
                    },
                    {
                        "text": t("excuse-btn-reject"),
                        "callback_data": ExcuseCb(t=reject, d="r").pack(),
                    },
                ]
            )
        if description.link is not None:
            rows.append(
                [link_button(t("excuse-btn-open"), description.link, self.urls)]
            )
        return rows
