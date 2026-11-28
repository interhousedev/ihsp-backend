"""The digital student card: show it, verify it by its permanent QR token, wallets."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.domain.errors import (
    StudentCardNotFoundError,
    StudentCardWalletUnavailableError,
)
from app.modules.identity.domain.student_card import (
    LyceumName,
    OwnCard,
    StudentCard,
    WalletAvailability,
    WalletPass,
    academic_year_of,
    card_url,
    course_of,
    new_card_token,
    owner_key,
)
from app.modules.identity.ports.student_card_facts import StudentCardFacts
from app.modules.identity.ports.student_card_tokens import StudentCardTokens
from app.modules.identity.ports.student_card_wallet import StudentCardWallet
from app.shared.clock import Clock
from app.shared.contracts.emis import EmisProfile, EmisSource
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.rate_limit import RateLimiter

REGENERATE_LIMIT_PER_HOUR = 10
WALLET_LIMIT_PER_HOUR = 20
LOOKUP_LIMIT_PER_MINUTE = 60


@dataclass(frozen=True, slots=True)
class CardPhoto:
    """The photo behind a card."""

    data: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class CardLogo:
    """The uploaded lyceum logo: its bytes and its public address."""

    data: bytes
    url: str


LogoReader = Callable[[], Awaitable[CardLogo | None]]


def _lyceum(profile: EmisProfile) -> LyceumName | None:
    name = profile.institution_name
    if name is None or not (name.uz or name.ru or name.en):
        return None
    return LyceumName(uz=name.uz, ru=name.ru, en=name.en)


class StudentCardService:
    """Builds the card from the account and EMIS; one permanent QR token each."""

    def __init__(
        self,
        *,
        directory: IdentityDirectory,
        emis: EmisSource,
        facts: StudentCardFacts,
        files: FilesApi,
        tokens: StudentCardTokens,
        wallet: StudentCardWallet,
        logo: LogoReader,
        limiter: RateLimiter,
        clock: Clock,
        org_name: str,
        share_origin: str,
    ) -> None:
        """Keep the ports."""
        self._directory = directory
        self._emis = emis
        self._facts = facts
        self._files = files
        self._tokens = tokens
        self._wallet = wallet
        self._logo = logo
        self._limiter = limiter
        self._clock = clock
        self._org_name = org_name
        self._share_origin = share_origin

    async def _build(
        self, user_id: UUID, *, public: bool
    ) -> tuple[StudentCard, UUID | None, EmisProfile]:
        user = await self._directory.get_user(user_id)
        if user is None:
            raise StudentCardNotFoundError()
        profile = await self._emis.profile(user_id)
        # A photo hidden from the public never reaches the verification page.
        hidden = public and user.hide_photo_from_public
        photo = None if hidden else user.photo_file_id
        card = StudentCard(
            first_name=user.first_name,
            last_name=user.last_name,
            middle_name=profile.middle_name or None,
            student_id=str(profile.emis_student_id),
            group=profile.group_name or None,
            course=course_of(profile.current_semester),
            academic_year=academic_year_of(self._clock.now().date()),
            org_name=self._org_name,
            lyceum_name=_lyceum(profile),
            direction=profile.direction,
            speciality=profile.speciality,
            has_photo=photo is not None,
        )
        return card, photo, profile

    def _availability(self) -> WalletAvailability:
        return WalletAvailability(
            apple=self._wallet.apple_enabled, google=self._wallet.google_enabled
        )

    async def card(self, user_id: UUID) -> OwnCard:
        """Return the student's own card with its QR token (made on first view)."""
        card, _, profile = await self._build(user_id, public=False)
        await self._facts.record_user_emis_facts(user_id=user_id, profile=profile)
        token = await self._tokens.ensure(user_id, new_card_token())
        return OwnCard(card, token, self._availability())

    async def regenerate(self, user_id: UUID) -> str:
        """Replace the QR token; the old code stops working at once."""
        await self._limiter.hit(
            f"student-card:regenerate:{user_id}",
            limit=REGENERATE_LIMIT_PER_HOUR,
            window_seconds=3600,
        )
        await self._build(user_id, public=False)
        token = new_card_token()
        await self._tokens.replace(user_id, token)
        return token

    async def _owner(self, token: str, client_ip: str | None) -> UUID:
        await self._limiter.hit(
            f"student-card:lookup:{client_ip or 'unknown'}",
            limit=LOOKUP_LIMIT_PER_MINUTE,
            window_seconds=60,
        )
        owner = await self._tokens.owner(token)
        if owner is None:
            raise StudentCardNotFoundError()
        return owner

    async def lookup(self, token: str, client_ip: str | None) -> StudentCard:
        """Return the card behind a token, as the public sees it."""
        card, _, _ = await self._build(await self._owner(token, client_ip), public=True)
        return card

    async def _read_photo(self, file_id: UUID) -> CardPhoto | None:
        ref = await self._files.get(file_id)
        if ref is None:
            return None
        return CardPhoto(await self._files.read_bytes(file_id), ref.content_type)

    async def photo(self, token: str, client_ip: str | None) -> CardPhoto:
        """Return the photo behind a token; not found when none or hidden."""
        _, file_id, _ = await self._build(
            await self._owner(token, client_ip), public=True
        )
        photo = await self._read_photo(file_id) if file_id else None
        if photo is None:
            raise StudentCardNotFoundError()
        return photo

    async def _wallet_pass(self, user_id: UUID) -> WalletPass:
        await self._limiter.hit(
            f"student-card:wallet:{user_id}",
            limit=WALLET_LIMIT_PER_HOUR,
            window_seconds=3600,
        )
        card, file_id, _ = await self._build(user_id, public=False)
        token = await self._tokens.ensure(user_id, new_card_token())
        photo = await self._read_photo(file_id) if file_id else None
        logo = await self._logo()
        return WalletPass(
            serial=owner_key(user_id),
            card=card,
            verify_url=card_url(self._share_origin, token),
            photo=photo.data if photo else None,
            logo=logo.data if logo else None,
            logo_url=logo.url if logo else None,
        )

    async def apple_pass(self, user_id: UUID) -> bytes:
        """Return the signed Apple Wallet pass of the student's card."""
        if not self._wallet.apple_enabled:
            raise StudentCardWalletUnavailableError()
        return self._wallet.apple_pass(await self._wallet_pass(user_id))

    async def google_save_url(self, user_id: UUID) -> str:
        """Return the "Add to Google Wallet" link of the student's card."""
        if not self._wallet.google_enabled:
            raise StudentCardWalletUnavailableError()
        return self._wallet.google_save_url(await self._wallet_pass(user_id))
