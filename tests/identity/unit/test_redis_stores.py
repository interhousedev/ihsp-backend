"""ID-14, ID-15, GEN-5: the Redis helpers behind OTP, throttling and revocation."""

from app.modules.identity.domain.errors import AccountLockedError
from app.modules.identity.infrastructure.redis.auth_epoch_cache import (
    RedisAuthEpochCache,
)
from app.modules.identity.infrastructure.redis.login_throttle import RedisLoginThrottle
from app.modules.identity.infrastructure.redis.otp_store import RedisOtpStore
from app.modules.identity.infrastructure.redis.revocation_list import (
    RedisRevocationList,
)
from app.modules.identity.infrastructure.redis.ticket_store import RedisTicketStore
from app.shared.base_error import RateLimitedError
from app.shared.ids import new_id

import pytest
from fakeredis.aioredis import FakeRedis


async def test_code_has_six_digits_and_works_once(redis: FakeRedis) -> None:
    """ID-14: 6 digits, single use."""
    store = RedisOtpStore(redis)

    code = await store.issue("login", "u1", cooldown=None)

    assert len(code) == 6 and code.isdigit()
    assert await store.verify("login", "u1", code) is True
    assert await store.verify("login", "u1", code) is False


async def test_only_the_hash_is_stored(redis: FakeRedis) -> None:
    """Codes are bearer secrets: Redis never holds the plain code."""
    store = RedisOtpStore(redis)

    code = await store.issue("login", "u1", cooldown=None)

    stored = await redis.hgetall("otp:login:u1")
    assert code not in stored.values()


async def test_third_wrong_attempt_invalidates_the_code(redis: FakeRedis) -> None:
    """ID-14: at most 3 attempts."""
    store = RedisOtpStore(redis)
    code = await store.issue("login", "u1", cooldown=None)
    wrong = "000000" if code != "000000" else "111111"

    assert [await store.attempts_left("login", "u1")] == [3]
    for _ in range(3):
        assert await store.verify("login", "u1", wrong) is False

    assert await store.verify("login", "u1", code) is False
    assert await store.attempts_left("login", "u1") == 0


async def test_codes_expire_after_five_minutes(redis: FakeRedis) -> None:
    """ID-14: the TTL is 300 seconds."""
    store = RedisOtpStore(redis)
    await store.issue("login", "u1", cooldown=None)

    assert 0 < await redis.ttl("otp:login:u1") <= 300


async def test_new_code_replaces_the_old_one(redis: FakeRedis) -> None:
    """Only the latest code is valid."""
    store = RedisOtpStore(redis)
    first = await store.issue("login", "u1", cooldown=None)
    second = await store.issue("login", "u1", cooldown=None)

    if first != second:
        assert await store.verify("login", "u1", first) is False
    assert await store.verify("login", "u1", second) is True


async def test_second_code_within_the_cooldown_is_refused(redis: FakeRedis) -> None:
    """ID-14: a new code only after 60 seconds."""
    store = RedisOtpStore(redis)
    await store.issue("login", "u1")

    with pytest.raises(RateLimitedError) as caught:
        await store.issue("login", "u1")

    assert 0 < caught.value.params["retry_after"] <= 60
    await store.issue("pw-reset", "u1")  # another purpose has its own cooldown


async def test_login_is_locked_after_five_failures_with_growing_windows(
    redis: FakeRedis,
) -> None:
    """ID-15: 1, 5 then 15 minutes."""
    throttle = RedisLoginThrottle(redis)
    user_id = new_id()
    for _ in range(4):
        await throttle.record_failure("Ali", "1.1.1.1", user_id)
    await throttle.check("ali", "1.1.1.1")

    await throttle.record_failure("ali", "1.1.1.1", user_id)
    with pytest.raises(AccountLockedError) as caught:
        await throttle.check("ALI", "1.1.1.1")
    assert caught.value.params["retry_after"] <= 60

    await redis.delete("lf-lock:ali:1.1.1.1")
    await throttle.record_failure("ali", "1.1.1.1", user_id)
    assert 60 < await redis.ttl("lf-lock:ali:1.1.1.1") <= 300
    await redis.delete("lf-lock:ali:1.1.1.1")
    await throttle.record_failure("ali", "1.1.1.1", user_id)
    assert 300 < await redis.ttl("lf-lock:ali:1.1.1.1") <= 900


async def test_lock_is_per_ip_and_cleared_by_a_success(redis: FakeRedis) -> None:
    """ID-15: a stranger's failures do not lock the owner out."""
    throttle = RedisLoginThrottle(redis)
    for _ in range(5):
        await throttle.record_failure("ali", "6.6.6.6", None)

    await throttle.check("ali", "7.7.7.7")
    with pytest.raises(AccountLockedError):
        await throttle.check("ali", "6.6.6.6")
    await throttle.reset("ali", "6.6.6.6")
    await throttle.check("ali", "6.6.6.6")


async def test_account_failures_are_counted_across_ips(redis: FakeRedis) -> None:
    """ID-15: the user is notified of repeated failures from any IP."""
    throttle = RedisLoginThrottle(redis)
    user_id = new_id()

    counts = [
        (await throttle.record_failure("ali", f"9.9.9.{i}", user_id)).for_account
        for i in range(3)
    ]

    assert counts == [1, 2, 3]


async def test_otp_failures_are_counted_per_account_and_ip(redis: FakeRedis) -> None:
    """ID-15: 10 failed codes a day block passwordless OTP for the IP."""
    throttle = RedisLoginThrottle(redis)
    user_id = new_id()

    for _ in range(3):
        await throttle.record_otp_failure(user_id, "1.1.1.1")

    assert await throttle.otp_failures(user_id, "1.1.1.1") == 3
    assert await throttle.otp_failures(user_id, "2.2.2.2") == 0


async def test_revocation_list_and_epoch_cache(redis: FakeRedis) -> None:
    """GEN-5: revoked ids and cached epochs."""
    revocations = RedisRevocationList(redis)
    epochs = RedisAuthEpochCache(redis)
    sid, user_id = new_id(), new_id()

    assert await revocations.is_revoked(sid) is False
    await revocations.revoke(sid)
    assert await revocations.is_revoked(sid) is True
    assert 600 < await redis.ttl(f"auth:revoked:{sid}")

    assert await epochs.get(user_id) is None
    await epochs.set(user_id, 4)
    assert await epochs.get(user_id) == 4


async def test_ticket_store_round_trip_with_ttl(redis: FakeRedis) -> None:
    """Tickets hold small JSON documents."""
    tickets = RedisTicketStore(redis)

    await tickets.put("t:1", {"a": 1}, ttl=60)

    assert await tickets.get("t:1") == {"a": 1}
    assert 0 < await redis.ttl("t:1") <= 60
    await tickets.delete("t:1")
    assert await tickets.get("t:1") is None
