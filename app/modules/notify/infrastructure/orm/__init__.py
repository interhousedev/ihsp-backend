"""ORM models of the notify module (schema ``notify``)."""

from app.modules.notify.infrastructure.orm.notification import Notification
from app.modules.notify.infrastructure.orm.push_subscription import PushSubscription

__all__ = ["Notification", "PushSubscription"]
