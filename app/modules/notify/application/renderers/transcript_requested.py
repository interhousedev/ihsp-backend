"""Telegram notice to the registrar with a Done button."""

from typing import Any

from app.modules.notify.application.describe import Description
from app.modules.notify.application.renderers.described import (
    Buttons,
    DescribedRenderer,
)
from app.shared.contracts.callbacks import TrCb
from app.shared.contracts.notify import RenderContext
from app.shared.notifications import NotificationType


class TranscriptRequestedRenderer(DescribedRenderer):
    """A transcript request with a Done button (the id is checked on the press)."""

    notification_type = NotificationType.TRANSCRIPT_REQUESTED

    def buttons(
        self, payload: dict[str, Any], ctx: RenderContext, description: Description
    ) -> Buttons | None:
        """Done, for the request in the payload."""
        t = self.i18n.get_context(ctx.locale)
        request = str(payload.get("request_id_b64", ""))
        if not request:
            return []
        return [
            [
                {
                    "text": t("notify-transcript-btn-done"),
                    "callback_data": TrCb(a="d", i=request).pack(),
                }
            ]
        ]
