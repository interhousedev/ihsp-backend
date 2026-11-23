"""Read values of course certificates, detached from the database session."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CertificateTemplate:
    """A certificate design: background and placed fields."""

    id: UUID
    course_id: UUID
    name: str
    background_file_id: UUID | None
    width_px: int
    height_px: int
    fields: list[dict[str, Any]]
    qr: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CoursePartner:
    """An organisation that co-issues the certificates of a course."""

    id: UUID
    course_id: UUID
    name: str
    url: str | None
    logo_file_id: UUID | None
    co_issued: bool


@dataclass(frozen=True, slots=True)
class IssuedCertificate:
    """An issued certificate with the snapshot printed on it."""

    id: UUID
    code: str
    course_id: UUID
    user_id: UUID
    tier_key: str
    tier_label: dict[str, str]
    holder_name: str
    course_title: str
    partner: dict[str, Any] | None
    template: dict[str, Any] | None
    score_pct: int
    issued_at: datetime
    revoked_at: datetime | None
    revoke_reason: str | None
