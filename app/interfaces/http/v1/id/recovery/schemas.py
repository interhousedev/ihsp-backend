"""Schemas of the recovery endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class PasswordRequestBody(BaseModel):
    """POST /v1/id/recovery/password/request."""

    login_or_email: str = Field(min_length=1, max_length=320)


class PasswordConfirmBody(BaseModel):
    """POST /v1/id/recovery/password/confirm."""

    login_or_email: str = Field(min_length=1, max_length=320)
    code: str = Field(min_length=1, max_length=16)
    new_password: str = Field(min_length=1, max_length=1000)


class OtpRecoveryRequestBody(BaseModel):
    """POST /v1/id/recovery/otp/request."""

    login: str = Field(min_length=1, max_length=100)


class OtpRecoveryConfirmBody(BaseModel):
    """POST /v1/id/recovery/otp/confirm."""

    login: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=16)


class OtpRecoveryConfirmResponse(BaseModel):
    """When the OTP reset takes effect."""

    effective_at: datetime


class OtpRecoveryCancelBody(BaseModel):
    """POST /v1/id/recovery/otp/cancel (the Cancel button in Telegram)."""

    request_id: UUID


class LoginRecoveryBody(BaseModel):
    """POST /v1/id/recovery/login."""

    email: EmailStr
