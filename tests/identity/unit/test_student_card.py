"""The student card token: resolves before the TTL, 404 after, no owner id."""

import hashlib
from dataclasses import asdict
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.modules.identity.application.student_card import StudentCardService
from app.modules.identity.domain.errors import StudentCardNotFoundError
from app.modules.identity.domain.student_card import course_of
from app.modules.identity.infrastructure.redis.ticket_store import RedisTicketStore
from app.shared.base_error import RateLimitedError
from app.shared.contracts.emis import EmisName, EmisProfile
from app.shared.rate_limit import RateLimiter
from tests.fakes.clock import FixedClock

import pytest
from fakeredis import FakeAsyncRedis

USER_ID = uuid4()
PHOTO_ID = uuid4()


def _profile() -> EmisProfile:
    return EmisProfile(
        emis_student_id=1,
        first_name="Ali",
        last_name="Valiyev",
        middle_name=None,
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
    def __init__(self, photo: bool) -> None:
        self.photo = photo

    async def get_user(self, user_id: UUID) -> SimpleNamespace:
        return SimpleNamespace(
            first_name="Ali",
            last_name="Valiyev",
            photo_file_id=PHOTO_ID if self.photo else None,
        )


class _Emis:
    async def profile(self, user_id: UUID) -> EmisProfile:
        return _profile()


class _Files:
    async def get(self, file_id: UUID) -> SimpleNamespace:
        return SimpleNamespace(content_type="image/png")

    async def read_bytes(self, file_id: UUID) -> bytes:
        return b"png"


def _service(
    redis: FakeAsyncRedis, clock: FixedClock, photo: bool = True
) -> StudentCardService:
    return StudentCardService(
        directory=_Directory(photo),  # type: ignore[arg-type]
        emis=_Emis(),  # type: ignore[arg-type]
        files=_Files(),  # type: ignore[arg-type]
        store=RedisTicketStore(redis),
        limiter=RateLimiter(redis),
        clock=clock,
    )


async def test_token_resolves_before_ttl_and_not_after(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    service = _service(redis, clock)
    issued = await service.issue(USER_ID)
    assert issued.refresh_in == 60

    clock.advance(seconds=119)
    shared = await service.lookup(issued.token, "1.2.3.4")
    assert shared.card.group == "2TN2"
    assert shared.card.course == 2
    assert shared.card.lyceum_name is not None
    assert shared.card.lyceum_name.ru == "Лицей"

    clock.advance(seconds=2)
    with pytest.raises(StudentCardNotFoundError):
        await service.lookup(issued.token, "1.2.3.4")


async def test_unknown_token_is_not_found(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    with pytest.raises(StudentCardNotFoundError):
        await _service(redis, clock).lookup("nope", None)


async def test_only_hash_is_stored_and_public_card_has_no_owner(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    service = _service(redis, clock)
    issued = await service.issue(USER_ID)
    keys = [k async for k in redis.scan_iter("student-card:*")]
    assert keys == ["student-card:" + hashlib.sha256(issued.token.encode()).hexdigest()]
    assert issued.token not in keys[0]

    shared = await service.lookup(issued.token, None)
    assert str(USER_ID) not in repr(asdict(shared))
    assert "user_id" not in asdict(shared.card)


async def test_photo_and_missing_photo(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    with_photo = _service(redis, clock)
    issued = await with_photo.issue(USER_ID)
    photo = await with_photo.photo(issued.token, None)
    assert (photo.data, photo.content_type) == (b"png", "image/png")

    without = _service(redis, clock, photo=False)
    issued = await without.issue(USER_ID)
    assert (await without.lookup(issued.token, None)).card.has_photo is False
    with pytest.raises(StudentCardNotFoundError):
        await without.photo(issued.token, None)


async def test_eleventh_issue_in_a_minute_is_limited(
    redis: FakeAsyncRedis, clock: FixedClock
) -> None:
    service = _service(redis, clock)
    for _ in range(10):
        await service.issue(USER_ID)
    with pytest.raises(RateLimitedError):
        await service.issue(USER_ID)


def test_course_of_semester() -> None:
    assert [course_of(s) for s in (1, 2, 3, 4, None)] == [1, 1, 2, 2, None]
