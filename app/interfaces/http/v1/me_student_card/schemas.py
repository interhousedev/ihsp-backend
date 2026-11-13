"""Schemas of the student card routes (own and public)."""

from datetime import datetime

from pydantic import BaseModel


class LyceumNameOut(BaseModel):
    """The lyceum name in the three languages."""

    uz: str
    ru: str
    en: str


class StudentCardResponse(BaseModel):
    """The student's own card."""

    first_name: str
    last_name: str
    group: str | None
    course: int | None
    lyceum_name: LyceumNameOut | None
    direction: str | None
    speciality: str | None
    has_photo: bool


class StudentCardTokenResponse(BaseModel):
    """A share token: shown as a QR code, valid for two minutes."""

    token: str
    expires_at: datetime
    refresh_in: int


class PublicStudentCardResponse(StudentCardResponse):
    """The card seen through a token; the owner's id is not part of it."""

    expires_at: datetime
