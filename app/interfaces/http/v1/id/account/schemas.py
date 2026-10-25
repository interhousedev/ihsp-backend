"""Schemas of the /v1/id/me endpoints."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.id.schemas import TelegramAccountResponse
from app.modules.identity.application.get_me import MeView
from app.shared.actor import Role
from app.shared.contracts.identity import UserPreferences

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserMeResponse(BaseModel):
    """UserMe."""

    id: UUID
    login: str | None
    first_name: str
    last_name: str
    middle_name: str | None
    roles: list[Role]
    status: str
    recovery_email: str | None
    otp_enabled: bool
    otp_via_email: bool
    emis_status: Literal["active", "needs_reauth"] | None
    mailbox: str | None
    photo_url: str | None
    preferences: UserPreferences
    telegram: list[TelegramAccountResponse]

    @classmethod
    def of(cls, view: MeView) -> "UserMeResponse":
        """Map the account view."""
        user = view.user
        return cls(
            id=user.id,
            login=user.login,
            first_name=user.first_name,
            last_name=user.last_name,
            middle_name=user.middle_name,
            roles=sorted(user.roles, key=lambda role: role.value),
            status=user.status.value,
            recovery_email=user.recovery_email,
            otp_enabled=user.otp_enabled,
            otp_via_email=user.otp_via_email,
            emis_status=user.emis_status,
            mailbox=view.mailbox,
            photo_url=view.photo_url,
            preferences=UserPreferences.model_validate(user.preferences),
            telegram=[TelegramAccountResponse.of(link) for link in view.telegram],
        )


class PreferencesPatchBody(BaseModel):
    """PATCH /v1/id/me/preferences: any subset of UserPreferences."""

    model_config = ConfigDict(extra="forbid")

    locale: Literal["uz", "ru", "en"] | None = None
    theme: Literal["system", "light", "dark"] | None = None
    marks_enabled: bool | None = None
    marks_types: list[Literal["lesson", "midterm", "final"]] | None = None
    marks_values: list[int] | None = None
    marks_subject_ids: list[UUID] | None = None
    alerts_drops: bool | None = None
    alerts_gpa_below: float | None = None
    alerts_semester_mark_below: float | None = None
    alerts_mark_below: int | None = None
    lessons_links_lead_min: int | None = None
    lessons_prompt_enabled: bool | None = None
    mail_forward_to_telegram: bool | None = None
    notify_push: bool | None = None
    today_cards: list[str] | None = None
    onboarding_dismissed: list[str] | None = None
    bottom_nav: list[str] | None = None
    seen_marks_at: datetime | None = None


class ChangePasswordBody(BaseModel):
    """POST /v1/id/me/password."""

    current_password: str = Field(min_length=1, max_length=1000)
    new_password: str = Field(min_length=1, max_length=1000)


class TelegramPatchBody(BaseModel):
    """PATCH /v1/id/me/telegram/{id}."""

    otp_delivery: bool


class OtpEnableBody(BaseModel):
    """POST /v1/id/me/otp/enable."""

    via_email: bool = False


class CodeBody(BaseModel):
    """A one-time code."""

    code: str = Field(min_length=1, max_length=16)


class OtpDisableBody(BaseModel):
    """POST /v1/id/me/otp/disable."""

    password: str = Field(min_length=1, max_length=1000)


class EmailChangeBody(BaseModel):
    """POST /v1/id/me/email/change."""

    password: str = Field(min_length=1, max_length=1000)
    new_email: EmailStr
