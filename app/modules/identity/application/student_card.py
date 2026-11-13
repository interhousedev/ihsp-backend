"""The digital student card: show it, share it for two minutes, look it up."""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.modules.identity.domain.errors import StudentCardNotFoundError
from app.modules.identity.domain.student_card import (
    CARD_REFRESH_SECONDS,
    CARD_TTL_SECONDS,
    CardSnapshot,
    IssuedToken,
    LyceumName,
    SharedCard,
    StudentCard,
    course_of,
    token_key,
)
from app.modules.identity.infrastructure.redis.ticket_store import RedisTicketStore
from app.shared.clock import Clock
from app.shared.contracts.emis import EmisProfile, EmisSource
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.rate_limit import RateLimiter

ISSUE_LIMIT_PER_MINUTE = 10
LOOKUP_LIMIT_PER_MINUTE = 60


@dataclass(frozen=True, slots=True)
class CardPhoto:
    """The photo behind a shared card."""

    data: bytes
    content_type: str


def _lyceum(profile: EmisProfile) -> LyceumName | None:
    name = profile.institution_name
    if name is None or not (name.uz or name.ru or name.en):
        return None
    return LyceumName(uz=name.uz, ru=name.ru, en=name.en)


def _dump(snapshot: CardSnapshot) -> dict[str, Any]:
    card = snapshot.card
    lyceum = card.lyceum_name
    return {
        "user_id": str(snapshot.user_id),
        "photo_file_id": (
            str(snapshot.photo_file_id) if snapshot.photo_file_id else None
        ),
        "expires_at": snapshot.expires_at.isoformat(),
        "first_name": card.first_name,
        "last_name": card.last_name,
        "group": card.group,
        "course": card.course,
        "lyceum_name": (
            {"uz": lyceum.uz, "ru": lyceum.ru, "en": lyceum.en} if lyceum else None
        ),
        "direction": card.direction,
        "speciality": card.speciality,
        "has_photo": card.has_photo,
    }


def _load(raw: dict[str, Any]) -> CardSnapshot:
    lyceum = raw["lyceum_name"]
    photo = raw["photo_file_id"]
    return CardSnapshot(
        user_id=UUID(raw["user_id"]),
        photo_file_id=UUID(photo) if photo else None,
        expires_at=datetime.fromisoformat(raw["expires_at"]),
        card=StudentCard(
            first_name=raw["first_name"],
            last_name=raw["last_name"],
            group=raw["group"],
            course=raw["course"],
            lyceum_name=LyceumName(**lyceum) if lyceum else None,
            direction=raw["direction"],
            speciality=raw["speciality"],
            has_photo=raw["has_photo"],
        ),
    )


class StudentCardService:
    """Builds the card from the account and EMIS and shares it by a short token."""

    def __init__(
        self,
        *,
        directory: IdentityDirectory,
        emis: EmisSource,
        files: FilesApi,
        store: RedisTicketStore,
        limiter: RateLimiter,
        clock: Clock,
    ) -> None:
        """Keep the ports."""
        self._directory = directory
        self._emis = emis
        self._files = files
        self._store = store
        self._limiter = limiter
        self._clock = clock

    async def _build(self, user_id: UUID) -> tuple[StudentCard, UUID | None]:
        user = await self._directory.get_user(user_id)
        if user is None:
            raise StudentCardNotFoundError()
        profile = await self._emis.profile(user_id)
        card = StudentCard(
            first_name=user.first_name,
            last_name=user.last_name,
            group=profile.group_name or None,
            course=course_of(profile.current_semester),
            lyceum_name=_lyceum(profile),
            direction=profile.direction,
            speciality=profile.speciality,
            has_photo=user.photo_file_id is not None,
        )
        return card, user.photo_file_id

    async def card(self, user_id: UUID) -> StudentCard:
        """Return the student's own card."""
        card, _ = await self._build(user_id)
        return card

    async def issue(self, user_id: UUID) -> IssuedToken:
        """Issue a token for two minutes; at most ten per minute per user."""
        await self._limiter.hit(
            f"student-card:issue:{user_id}",
            limit=ISSUE_LIMIT_PER_MINUTE,
            window_seconds=60,
        )
        card, photo = await self._build(user_id)
        expires_at = self._clock.now() + timedelta(seconds=CARD_TTL_SECONDS)
        token = secrets.token_urlsafe(24)
        snapshot = CardSnapshot(user_id, photo, card, expires_at)
        await self._store.put(token_key(token), _dump(snapshot), ttl=CARD_TTL_SECONDS)
        return IssuedToken(token, expires_at, CARD_REFRESH_SECONDS)

    async def _snapshot(self, token: str, client_ip: str | None) -> CardSnapshot:
        await self._limiter.hit(
            f"student-card:lookup:{client_ip or 'unknown'}",
            limit=LOOKUP_LIMIT_PER_MINUTE,
            window_seconds=60,
        )
        raw = await self._store.get(token_key(token))
        if raw is None:
            raise StudentCardNotFoundError()
        snapshot = _load(raw)
        if snapshot.expires_at <= self._clock.now():
            raise StudentCardNotFoundError()
        return snapshot

    async def lookup(self, token: str, client_ip: str | None) -> SharedCard:
        """Return the card behind a token, without the owner."""
        snapshot = await self._snapshot(token, client_ip)
        return SharedCard(snapshot.card, snapshot.expires_at)

    async def photo(self, token: str, client_ip: str | None) -> CardPhoto:
        """Return the photo behind a token; not found without a photo."""
        snapshot = await self._snapshot(token, client_ip)
        if snapshot.photo_file_id is None:
            raise StudentCardNotFoundError()
        ref = await self._files.get(snapshot.photo_file_id)
        if ref is None:
            raise StudentCardNotFoundError()
        data = await self._files.read_bytes(snapshot.photo_file_id)
        return CardPhoto(data, ref.content_type)
