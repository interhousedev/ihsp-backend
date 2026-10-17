"""Schemas of the authenticator app (TOTP) and passkey endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.identity.application.manage_passkeys import SecurityOverview
from app.modules.identity.domain.factors import Passkey

from pydantic import BaseModel, Field


class PasskeyResponse(BaseModel):
    """One passkey of the user (no key material)."""

    id: UUID
    name: str
    transports: list[str]
    backed_up: bool
    created_at: datetime
    last_used_at: datetime | None

    @classmethod
    def of(cls, passkey: Passkey) -> "PasskeyResponse":
        """Map the entity."""
        return cls(
            id=passkey.id,
            name=passkey.name,
            transports=passkey.transports,
            backed_up=passkey.backed_up,
            created_at=passkey.created_at,
            last_used_at=passkey.last_used_at,
        )


class SecurityResponse(BaseModel):
    """GET /v1/id/me/security."""

    totp_enabled: bool
    recovery_codes_left: int
    password_login_enabled: bool
    passkeys: list[PasskeyResponse]

    @classmethod
    def of(cls, overview: SecurityOverview) -> "SecurityResponse":
        """Map the use case result."""
        return cls(
            totp_enabled=overview.totp_enabled,
            recovery_codes_left=overview.recovery_codes_left,
            password_login_enabled=overview.password_login_enabled,
            passkeys=[PasskeyResponse.of(p) for p in overview.passkeys],
        )


class TotpSetupResponse(BaseModel):
    """POST /v1/id/me/totp/setup: show ``otpauth_uri`` as a QR code."""

    secret: str
    otpauth_uri: str


class TotpCodeBody(BaseModel):
    """A 6-digit code (or, to disable, a recovery code)."""

    code: str = Field(min_length=6, max_length=16)


class RecoveryCodesResponse(BaseModel):
    """One-time recovery codes, shown once."""

    recovery_codes: list[str]


class WebAuthnOptionsResponse(BaseModel):
    """PublicKeyCredentialCreationOptions / RequestOptions as JSON (base64url)."""

    options: dict[str, Any]


class PasskeyRegisterBody(BaseModel):
    """POST /v1/id/me/passkeys: the browser's RegistrationResponseJSON."""

    credential: dict[str, Any]
    name: str = Field(default="", max_length=100)


class PasskeyRenameBody(BaseModel):
    """PATCH /v1/id/me/passkeys/{id}."""

    name: str = Field(min_length=1, max_length=100)


class TotpLoginBody(BaseModel):
    """POST /v1/id/login/totp."""

    login_challenge: str = Field(min_length=1)
    ticket: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=6, max_length=16)


class PasskeyOptionsBody(BaseModel):
    """POST /v1/id/login/passkey/options."""

    login_challenge: str = Field(min_length=1)


class PasskeyLoginBody(BaseModel):
    """POST /v1/id/login/passkey: the browser's AuthenticationResponseJSON."""

    login_challenge: str = Field(min_length=1)
    credential: dict[str, Any]
    remember: bool = False
