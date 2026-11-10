"""Entities of the faces module."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import sqrt
from uuid import UUID

RETENTION_DAYS = 7
NAME_MAX = 80


class Direction(StrEnum):
    """Which way a person went through the entrance."""

    IN = "in"
    OUT = "out"


class CallStatus(StrEnum):
    """What a device call came to."""

    MATCHED = "matched"
    NO_MATCH = "no_match"
    NO_FACE = "no_face"
    MULTIPLE_FACES = "multiple_faces"


@dataclass(slots=True)
class FaceProfile:
    """A user's face embedding; `locked` means staff set it."""

    user_id: UUID
    embedding: list[float]
    photo_file_id: UUID
    uploaded_by: UUID
    locked: bool
    updated_at: datetime


@dataclass(slots=True)
class Device:
    """An entrance device; the secret token is never kept, only its hash."""

    id: UUID
    name: str
    key_prefix: str
    key_hash: str
    created_by: UUID
    created_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DeviceCall:
    """One request from a device."""

    id: UUID
    device_id: UUID
    at: datetime
    status: CallStatus
    matched_user_id: UUID | None
    excused: bool | None


@dataclass(frozen=True, slots=True)
class Passage:
    """A recognised student passing the entrance."""

    id: UUID
    device_id: UUID
    user_id: UUID
    at: datetime
    direction: Direction
    excused: bool


def normalize_name(value: str) -> str | None:
    """Return the trimmed device name, or None when empty or too long."""
    name = " ".join(value.split())
    return name if 0 < len(name) <= NAME_MAX else None


def cosine(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity of two vectors (0 for a zero vector)."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = sqrt(sum(x * x for x in a)) * sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def best_match(
    probe: list[float], candidates: list[tuple[UUID, list[float]]], threshold: float
) -> UUID | None:
    """Return the user whose embedding is most similar, if at or over the threshold."""
    best_id: UUID | None = None
    best_score = threshold
    for user_id, embedding in candidates:
        score = cosine(probe, embedding)
        if score >= best_score:
            best_id, best_score = user_id, score
    return best_id
