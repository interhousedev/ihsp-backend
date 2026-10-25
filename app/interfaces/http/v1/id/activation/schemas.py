"""Schemas of the staff activation endpoints."""

from app.modules.identity.application.activation_info import ActivationInfoResult

from pydantic import BaseModel, EmailStr, Field


class ActivationInfoResponse(BaseModel):
    """GET /v1/id/activation/{token}."""

    first_name: str
    last_name: str
    login: str | None
    requires_otp: bool

    @classmethod
    def of(cls, info: ActivationInfoResult) -> "ActivationInfoResponse":
        """Map the use case result."""
        return cls(
            first_name=info.first_name,
            last_name=info.last_name,
            login=info.login,
            requires_otp=info.requires_otp,
        )


class ActivationEmailBody(BaseModel):
    """POST /v1/id/activation/{token}/email."""

    email: EmailStr


class ActivateBody(BaseModel):
    """POST /v1/id/activation/{token}.

    The email and its code are optional for a password reset link of an account
    whose email is already verified.
    """

    password: str = Field(min_length=1, max_length=1000)
    email: EmailStr | None = None
    email_code: str | None = Field(default=None, max_length=16)


class RedirectResponseBody(BaseModel):
    """Where to go after activation."""

    redirect_to: str
