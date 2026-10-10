"""ORM models of the admin module (schema ``admin``)."""

from app.modules.admin.infrastructure.orm.broadcast import Broadcast
from app.modules.admin.infrastructure.orm.platform_setting import PlatformSetting

__all__ = ["Broadcast", "PlatformSetting"]
