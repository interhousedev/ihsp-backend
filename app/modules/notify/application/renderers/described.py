"""Base of the simple renderers: bold title, plain body, optional buttons."""

from typing import Any, ClassVar

from app.modules.notify.application.describe import Description, describe
from app.modules.notify.application.format import esc
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderContext, RenderedMessage
from app.shared.i18n.core import I18nCore
from app.shared.notifications import NotificationType

Buttons = list[list[dict[str, Any]]]


def is_staff(user: UserRef) -> bool:
    """Return True for teachers who are not also students (they use the staff app)."""
    return Role.TEACHER in user.roles and Role.STUDENT not in user.roles


def link_button(text: str, link: str, urls: UrlsSettings) -> dict[str, Any]:
    """Button that opens a mini app for student and staff links, else a URL."""
    if link.startswith((urls.sp, urls.staff)):
        return {"text": text, "web_app_url": link}
    return {"text": text, "url": link}


class DescribedRenderer:
    """Renders `describe()` as Telegram HTML; subclasses add buttons."""

    notification_type: ClassVar[NotificationType]
    link_button_key: ClassVar[str | None] = None

    def __init__(self, i18n: I18nCore, urls: UrlsSettings) -> None:
        """Store translations and the app URLs."""
        self.i18n = i18n
        self.urls = urls

    async def __call__(
        self, payload: dict[str, Any], ctx: RenderContext
    ) -> RenderedMessage | None:
        """Render the notification for one user."""
        description = describe(
            self.notification_type,
            payload,
            ctx.locale,
            i18n=self.i18n,
            urls=self.urls,
            staff=is_staff(ctx.user),
        )
        return RenderedMessage(
            text_html=self.text(description),
            buttons=self.buttons(payload, ctx, description),
        )

    def text(self, description: Description) -> str:
        """Bold title and, when present, the escaped body below it."""
        title = f"<b>{esc(description.title)}</b>"
        return f"{title}\n{esc(description.body)}" if description.body else title

    def buttons(
        self, payload: dict[str, Any], ctx: RenderContext, description: Description
    ) -> Buttons | None:
        """One button to the described page when the type names a button text."""
        if self.link_button_key is None or description.link is None:
            return None
        label = self.i18n.t(ctx.locale, self.link_button_key)
        return [[link_button(label, description.link, self.urls)]]
