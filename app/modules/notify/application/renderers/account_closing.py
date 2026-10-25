"""Notice that the account will be closed."""

from app.modules.notify.application.renderers.described import DescribedRenderer
from app.shared.notifications import NotificationType


class AccountClosingRenderer(DescribedRenderer):
    """Notice that the account will be closed."""

    notification_type = NotificationType.ACCOUNT_CLOSING
