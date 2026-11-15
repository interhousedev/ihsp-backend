"""Request and response models of the Telegram bots routes (Administration only)."""

from datetime import datetime
from uuid import UUID

from app.modules.admin.application.bot_admin import AnnouncementResult, BotView
from app.modules.admin.domain.telegram_bot import ALL_FEATURES

from pydantic import BaseModel, Field

TOKEN_FIELD = Field(
    min_length=20, max_length=200, description="The BotFather token; never returned."
)
OTP_FIELD = Field(
    min_length=4, max_length=12, description="Step-up code from POST /v1/id/me/step-up."
)


class BotOut(BaseModel):
    """One bot; the token appears only as a mask of its last characters."""

    id: UUID
    name: str
    username: str
    enabled: bool
    is_default: bool
    features: dict[str, bool] = Field(
        description="ai_agent, open_ai_agent, commands, notifications, "
        "announcements, mini_app."
    )
    token_mask: str
    members: int = Field(description="Linked users who wrote to this bot.")
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, view: BotView) -> "BotOut":
        """Map a use case view."""
        bot = view.bot
        return cls(
            id=bot.id,
            name=bot.name,
            username=bot.username,
            enabled=bot.enabled,
            is_default=bot.is_default,
            features={
                str(f): bot.features.get(f, bot.is_default) for f in ALL_FEATURES
            },
            token_mask=f"…{bot.token_hint}",
            members=view.members,
            created_at=bot.created_at,
            updated_at=bot.updated_at,
        )


class BotsResponse(BaseModel):
    """Every registered bot, the default first."""

    items: list[BotOut]


class BotCreateBody(BaseModel):
    """Register a bot; the token is checked with Telegram's getMe."""

    name: str = Field(min_length=1, max_length=64)
    token: str = TOKEN_FIELD
    otp_code: str = OTP_FIELD


class BotPatchBody(BaseModel):
    """Change some fields; omitted fields stay. Needs a fresh step-up code."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None
    features: dict[str, bool] | None = None
    otp_code: str = OTP_FIELD


class BotTokenBody(BaseModel):
    """A new token for the same bot."""

    token: str = TOKEN_FIELD
    otp_code: str = OTP_FIELD


class AnnouncementBody(BaseModel):
    """Send a draft broadcast through the selected bots, in this order."""

    broadcast_id: UUID
    bot_ids: list[UUID] = Field(min_length=1, max_length=50)
    otp_code: str = OTP_FIELD


class AnnouncementOut(BaseModel):
    """Recipients in total and per bot."""

    broadcast_id: UUID
    recipients: int
    per_bot: dict[UUID, int]

    @classmethod
    def of(cls, result: AnnouncementResult) -> "AnnouncementOut":
        """Map the use case result."""
        return cls(
            broadcast_id=result.broadcast_id,
            recipients=result.recipients,
            per_bot=dict(result.per_bot),
        )
