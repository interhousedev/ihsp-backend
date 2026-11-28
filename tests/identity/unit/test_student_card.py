"""The student card: a permanent QR token, revoked by regeneration, no owner id."""

from dataclasses import asdict
from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.modules.identity.application.student_card import StudentCardService
from app.modules.identity.domain.errors import (
    StudentCardNotFoundError,
    StudentCardWalletUnavailableError,
)
from app.modules.identity.domain.student_card import (
    WalletPass,
    academic_year_of,
    course_of,
)
from app.shared.base_error import RateLimitedError
from app.shared.contracts.emis import EmisName, EmisProfile
from app.shared.rate_limit import RateLimiter
from tests.fakes.clock import FixedClock
from tests.fakes.student_card_tokens import FakeStudentCardTokens

import pytest
from fakeredis import FakeAsyncRedis

USER_ID = uuid4()
PHOTO_ID = uuid4()


def _profile() -> EmisProfile:
    return EmisProfile(
        emis_student_id=4711,
        first_name="Ali",
        last_name="Valiyev",
        middle_name="Akmalovich",
        institution_id=1,
        group_emis_id=2,
        group_name="2TN2",
        current_semester=3,
        curriculum_id=4,
        institution_name=EmisName(uz="Litsey", ru="Лицей", en="Lyceum"),
        direction="Aniq fanlar-2",
        speciality="Texnik-dasturchi",
    )


class _Directory:
    def __init__(self, photo: bool, hidden: bool) -> None:
        self.photo = photo
        self.hidden = hidden

    async def get_user(self, user_id: UUID) -> SimpleNamespace:
        return SimpleNamespace(
            first_name="Ali",
            last_name="Valiyev",
            photo_file_id=PHOTO_ID if self.photo else None,
            hide_photo_from_public=self.hidden,
        )


class _Emis:
    async def profile(self, user_id: UUID) -> EmisProfile:
        return _profile()


class _Files:
    async def get(self, file_id: UUID) -> SimpleNamespace:
        return SimpleNamespace(content_type="image/png")

    async def read_bytes(self, file_id: UUID) -> bytes:
        return b"png"


class _Facts:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, EmisProfile]] = []

    async def record_user_emis_facts(
        self, *, user_id: UUID, profile: EmisProfile
    ) -> None:
        self.calls.append((user_id, profile))


class _Wallet:
    def __init__(self, enabled: bool) -> None:
        self.apple_enabled = enabled
        self.google_enabled = enabled
        self.passes: list[WalletPass] = []

    def apple_pass(self, data: WalletPass) -> bytes:
        self.passes.append(data)
        return b"pkpass"

    def google_save_url(self, data: WalletPass) -> str:
        self.passes.append(data)
        return "https://pay.google.com/gp/v/save/jwt"


async def _no_logo() -> None:
    return None


def _service(
    redis: FakeAsyncRedis,
    clock: FixedClock,
    *,
    photo: bool = True,
    hidden: bool = False,
    facts: _Facts | None = None,
    wallet: _Wallet | None = None,
    tokens: FakeStudentCardTokens | None = None,
) -> StudentCardService:
    return StudentCardService(
        directory=_Directory(photo, hidden),  # type: ignore[arg-type]
        emis=_Emis(),  # type: ignore[arg-type]
        files=_Files(),  # type: ignore[arg-type]
        facts=facts or _Facts(),  # type: ignore[arg-type]
        tokens=tokens or FakeStudentCardTokens(),
        wallet=wallet or _Wallet(False),
        logo=_no_logo,
        limiter=RateLimiter(redis),
        clock=clock,
        org_name="Academic Lyceum",
        share_origin="https://share.example/",
    )


async def test_card_shows_full_name_id_year_and_persists_facts(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    facts = _Facts()
    own = await _service(redis, clock, facts=facts).card(USER_ID)
    assert own.card.full_name == "Valiyev Ali Akmalovich"
    assert own.card.student_id == "4711"
    assert own.card.academic_year == "2026–2027"
    assert own.card.org_name == "Academic Lyceum"
    assert own.card.speciality == "Texnik-dasturchi"
    assert own.card.course == 2
    assert own.wallet.apple is False and own.wallet.google is False
    assert facts.calls == [(USER_ID, _profile())]


async def test_token_is_permanent_until_regenerated(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    service = _service(redis, clock)
    first = (await service.card(USER_ID)).qr_token
    clock.advance(days=400)
    assert (await service.card(USER_ID)).qr_token == first
    assert (await service.lookup(first, "1.2.3.4")).group == "2TN2"

    second = await service.regenerate(USER_ID)
    assert second != first
    assert (await service.card(USER_ID)).qr_token == second
    with pytest.raises(StudentCardNotFoundError):
        await service.lookup(first, "1.2.3.4")
    assert (await service.lookup(second, None)).student_id == "4711"


async def test_unknown_token_is_not_found(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    with pytest.raises(StudentCardNotFoundError):
        await _service(redis, clock).lookup("nope", None)


async def test_public_card_has_no_owner(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    service = _service(redis, clock)
    token = (await service.card(USER_ID)).qr_token
    card = await service.lookup(token, None)
    assert str(USER_ID) not in repr(asdict(card))


async def test_photo_missing_and_hidden_from_public(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    with_photo = _service(redis, clock)
    token = (await with_photo.card(USER_ID)).qr_token
    photo = await with_photo.photo(token, None)
    assert (photo.data, photo.content_type) == (b"png", "image/png")

    for service in (
        _service(redis, clock, photo=False),
        _service(redis, clock, hidden=True),
    ):
        token = (await service.card(USER_ID)).qr_token
        assert (await service.lookup(token, None)).has_photo is False
        with pytest.raises(StudentCardNotFoundError):
            await service.photo(token, None)

    hidden = _service(redis, clock, hidden=True)
    assert (await hidden.card(USER_ID)).card.has_photo is True


async def test_eleventh_regeneration_in_an_hour_is_limited(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    service = _service(redis, clock)
    for _ in range(10):
        await service.regenerate(USER_ID)
    with pytest.raises(RateLimitedError):
        await service.regenerate(USER_ID)


async def test_wallets_off_without_settings_and_on_with_them(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    off = _service(redis, clock)
    with pytest.raises(StudentCardWalletUnavailableError):
        await off.apple_pass(USER_ID)
    with pytest.raises(StudentCardWalletUnavailableError):
        await off.google_save_url(USER_ID)

    wallet = _Wallet(True)
    on = _service(redis, clock, wallet=wallet)
    token = (await on.card(USER_ID)).qr_token
    assert await on.apple_pass(USER_ID) == b"pkpass"
    assert (await on.google_save_url(USER_ID)).startswith("https://pay.google.com/")
    data = wallet.passes[0]
    assert data.verify_url == f"https://share.example/card/?t={token}"
    assert data.photo == b"png"
    assert data.serial == f"card-{USER_ID.hex}"


def test_course_of_semester() -> None:
    assert [course_of(s) for s in (1, 2, 3, 4, None)] == [1, 1, 2, 2, None]


def test_academic_year_turns_on_first_of_september() -> None:
    assert academic_year_of(date(2026, 8, 31)) == "2025–2026"
    assert academic_year_of(date(2026, 9, 1)) == "2026–2027"
