"""The offer of new MCP scopes, with the two decision buttons (A7)."""

from typing import Any

from app.modules.notify.application.describe import Description
from app.modules.notify.application.renderers.described import (
    Buttons,
    DescribedRenderer,
    link_button,
)
from app.shared.contracts.callbacks import McpScopeCb
from app.shared.contracts.notify import RenderContext
from app.shared.notifications import NotificationType


class McpScopeOfferRenderer(DescribedRenderer):
    """Names read and write scopes apart; each button carries the offer's token."""

    notification_type = NotificationType.MCP_SCOPE_OFFER

    def buttons(
        self, payload: dict[str, Any], ctx: RenderContext, description: Description
    ) -> Buttons | None:
        """Give, don't give, and a link to the connectors page."""
        t = self.i18n.get_context(ctx.locale)
        token = str(payload.get("token", ""))
        rows: Buttons = []
        if token:
            rows.append(
                [
                    {
                        "text": t("mcp-offer-btn-grant"),
                        "callback_data": McpScopeCb(t=token, d="g").pack(),
                    },
                    {
                        "text": t("mcp-offer-btn-decline"),
                        "callback_data": McpScopeCb(t=token, d="n").pack(),
                    },
                ]
            )
        if description.link is not None:
            rows.append(
                [link_button(t("mcp-offer-btn-manage"), description.link, self.urls)]
            )
        return rows
