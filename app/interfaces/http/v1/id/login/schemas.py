"""Schemas of the Hydra login, consent and logout endpoints."""

from datetime import date
from typing import Literal

from app.modules.identity.application.get_consent_info import ConsentInfo
from app.modules.identity.application.get_login_info import LoginInfo
from app.modules.identity.application.login_result import LoginResult

from pydantic import BaseModel, Field


class LoginInfoResponse(BaseModel):
    """GET /v1/id/login."""

    client_id: str
    client_name: str
    skip: bool
    requires_second_factor: bool
    redirect_to: str | None

    @classmethod
    def of(cls, info: LoginInfo) -> "LoginInfoResponse":
        """Map the use case result."""
        return cls(
            client_id=info.client_id,
            client_name=info.client_name,
            skip=info.skip,
            requires_second_factor=info.requires_second_factor,
            redirect_to=info.redirect_to,
        )


class SecondFactorResponse(BaseModel):
    """A code was sent; send it back with the ticket."""

    method: Literal["otp"] = "otp"
    ticket: str
    channels: list[str]


class PasswordChangeResponse(BaseModel):
    """The password was set by an administrator: send a new one with the ticket."""

    ticket: str


class RestoreResponse(BaseModel):
    """The account is scheduled for deletion on ``deletes_on``: restore or decline."""

    ticket: str
    deletes_on: date


class LoginResultResponse(BaseModel):
    """A redirect, a second factor, a forced password change or a restore offer."""

    redirect_to: str | None = None
    second_factor: SecondFactorResponse | None = None
    password_change: PasswordChangeResponse | None = None
    restore: RestoreResponse | None = None

    @classmethod
    def of(cls, result: LoginResult) -> "LoginResultResponse":
        """Map the use case result."""
        factor = result.second_factor
        return cls(
            redirect_to=result.redirect_to,
            second_factor=(
                SecondFactorResponse(ticket=factor.ticket, channels=factor.channels)
                if factor
                else None
            ),
            password_change=(
                PasswordChangeResponse(ticket=result.password_change.ticket)
                if result.password_change
                else None
            ),
            restore=(
                RestoreResponse(
                    ticket=result.restore.ticket, deletes_on=result.restore.deletes_on
                )
                if result.restore
                else None
            ),
        )


class LoginBody(BaseModel):
    """POST /v1/id/login."""

    login_challenge: str = Field(min_length=1)
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1000)
    remember: bool = False


class NewPasswordLoginBody(BaseModel):
    """POST /v1/id/login/password: finish a login with a new password."""

    login_challenge: str = Field(min_length=1)
    ticket: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=1000)


class RestoreBody(BaseModel):
    """POST /v1/id/login/restore and /login/restore/decline."""

    login_challenge: str = Field(min_length=1)
    ticket: str = Field(min_length=1, max_length=200)


class OtpRequestBody(BaseModel):
    """POST /v1/id/login/otp/request (the mini app page sends an empty challenge)."""

    login_challenge: str = ""
    login: str = Field(min_length=1, max_length=100)


class SentResponse(BaseModel):
    """Always the same answer, whether or not a code was sent."""

    sent: bool = True


class OtpLoginBody(BaseModel):
    """POST /v1/id/login/otp."""

    login_challenge: str = Field(min_length=1)
    login: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=16)
    ticket: str | None = None


class ConsentInfoResponse(BaseModel):
    """GET /v1/id/consent."""

    client_id: str
    client_name: str
    verified: bool
    redirect_domain: str
    server: Literal["student", "lms", "admin"] | None
    requested_scopes: list[str]
    requires_otp: bool
    redirect_to: str | None

    @classmethod
    def of(cls, info: ConsentInfo) -> "ConsentInfoResponse":
        """Map the use case result."""
        return cls(
            client_id=info.client_id,
            client_name=info.client_name,
            verified=info.verified,
            redirect_domain=info.redirect_domain,
            server=info.server,
            requested_scopes=info.requested_scopes,
            requires_otp=info.requires_otp,
            redirect_to=info.redirect_to,
        )


class ConsentBody(BaseModel):
    """POST /v1/id/consent."""

    consent_challenge: str = Field(min_length=1)
    accept: bool
    grant_scopes: list[str] = []
    otp_code: str | None = None


class RedirectToResponse(BaseModel):
    """Where to send the browser next."""

    redirect_to: str


class ConsentOtpBody(BaseModel):
    """POST /v1/id/consent/otp."""

    consent_challenge: str = Field(min_length=1)
