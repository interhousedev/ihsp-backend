"""Schemas of the Telegram mini app login page endpoints."""

from pydantic import BaseModel, Field


class TelegramStatusBody(BaseModel):
    """POST /v1/id/telegram/status."""

    init_data: str = Field(min_length=1)


class TelegramStatusResponse(BaseModel):
    """Is the Telegram account linked, and to which login."""

    linked: bool
    login: str | None


class TelegramLoginBody(BaseModel):
    """POST /v1/id/telegram/login."""

    init_data: str = Field(min_length=1)
    login: str = Field(min_length=1, max_length=100)
    password: str | None = Field(default=None, max_length=1000)
    otp_code: str | None = Field(default=None, max_length=16)


class TelegramLinkedResponse(BaseModel):
    """The Telegram account is linked."""

    linked: bool = True
    login: str | None


class TelegramOtpRequestBody(BaseModel):
    """POST /v1/id/telegram/otp/request."""

    init_data: str = Field(min_length=1)
    login: str = Field(min_length=1, max_length=100)
