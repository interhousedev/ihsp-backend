"""ORM models of the admin module (schema ``admin``)."""

from app.modules.admin.infrastructure.orm.ai_access import AiAccessRow
from app.modules.admin.infrastructure.orm.broadcast import Broadcast
from app.modules.admin.infrastructure.orm.limit_extension import LimitExtensionRow
from app.modules.admin.infrastructure.orm.platform_setting import PlatformSetting
from app.modules.admin.infrastructure.orm.telegram_bot import (
    TelegramBotMemberRow,
    TelegramBotRow,
)

__all__ = [
    "AiAccessRow",
    "Broadcast",
    "LimitExtensionRow",
    "PlatformSetting",
    "TelegramBotMemberRow",
    "TelegramBotRow",
]
