"""Schemas of the student card routes (own and public)."""

from pydantic import BaseModel


class LyceumNameOut(BaseModel):
    """The lyceum name in the three languages, as EMIS gives it."""

    uz: str
    ru: str
    en: str


class PublicStudentCardResponse(BaseModel):
    """The card as a verifier sees it through the QR code; no owner id."""

    first_name: str
    last_name: str
    middle_name: str | None
    full_name: str
    student_id: str | None
    group: str | None
    course: int | None
    academic_year: str
    org_name: str
    lyceum_name: LyceumNameOut | None
    direction: str | None
    speciality: str | None
    has_photo: bool


class WalletAvailabilityOut(BaseModel):
    """Which wallet buttons to show: a wallet without settings is off."""

    apple: bool
    google: bool


class StudentCardResponse(PublicStudentCardResponse):
    """The student's own card with its permanent QR token."""

    qr_token: str
    wallet: WalletAvailabilityOut


class StudentCardTokenResponse(BaseModel):
    """The new permanent QR token; the previous one no longer works."""

    token: str


class GoogleWalletLinkResponse(BaseModel):
    """The "Add to Google Wallet" link."""

    url: str
