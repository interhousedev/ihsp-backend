"""ID-EMIS-LOGIN: an EMIS ID resolves to the login of its active account.

Covers the registered, unregistered, blocked, rate-limited and malformed cases, the
masked audit row and the response floor that keeps the answers close in time.
"""

from app.modules.identity.application.register_models import AccountSnapshot
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.resolve_emis_login import ResolveEmisLogin
from app.modules.identity.domain.emis_login import (
    EMIS_LOGIN_LOOKUP,
    EmisLoginInvalidError,
    EmisLoginNotFoundError,
)
from app.shared.actor import Role
from app.shared.base_error import RateLimitedError
from app.shared.contracts.identity import UserStatus
from app.shared.rate_limit import RateLimiter
from tests.fakes.clock import FixedClock
from tests.fakes.identity.uow import FakeIdentityUnitOfWork, IdentityStore
from tests.identity.emis.fakes import (
    FakeEmisUnitOfWork,
    InMemoryAccountRepository,
    Ledger,
    make_account,
)
from tests.identity.support import make_user

import pytest
from fakeredis.aioredis import FakeRedis

EMIS_ID = "78201"
CTX = RequestContext(ip="203.0.113.5", user_agent="pytest/1.0")


class Recorder:
    """Records the pauses the use case asks for, without waiting."""

    def __init__(self) -> None:
        """Start with no pauses."""
        self.pauses: list[float] = []

    async def sleep(self, seconds: float) -> None:
        """Remember the pause."""
        self.pauses.append(seconds)


def make_resolver(
    redis: FakeRedis,
    repo: InMemoryAccountRepository,
    ledger: Ledger,
    *,
    floor_seconds: float = 0.0,
    recorder: Recorder | None = None,
    teachers: IdentityStore | None = None,
) -> ResolveEmisLogin:
    """The use case over in-memory accounts, teachers and the fakeredis limiter."""
    recorder = recorder or Recorder()
    identity = teachers or IdentityStore()
    clock = FixedClock()

    def uow_factory() -> FakeEmisUnitOfWork:
        return FakeEmisUnitOfWork(repo, ledger)

    def teacher_uow_factory() -> FakeIdentityUnitOfWork:
        return FakeIdentityUnitOfWork(identity, clock)

    return ResolveEmisLogin(
        uow_factory=uow_factory,
        teacher_uow_factory=teacher_uow_factory,
        rate_limiter=RateLimiter(redis),
        floor_seconds=floor_seconds,
        monotonic=lambda: 0.0,
        sleep=recorder.sleep,
    )


def accounts_with(*accounts: AccountSnapshot) -> InMemoryAccountRepository:
    """A repository holding the given account snapshots."""
    repo = InMemoryAccountRepository()
    for account in accounts:
        repo.add(account)
    return repo


async def test_registered_emis_id_resolves_to_the_account_login(
    redis: FakeRedis,
) -> None:
    """ID-EMIS-LOGIN: an active student's EMIS ID gives back the login."""
    account = make_account(emis_student_id=int(EMIS_ID), login="brastilov.aleksey")
    ledger = Ledger()
    resolver = make_resolver(redis, accounts_with(account), ledger)

    resolved = await resolver.execute(EMIS_ID, ctx=CTX)

    assert resolved.login == "brastilov.aleksey"


async def test_unregistered_emis_id_is_not_found(redis: FakeRedis) -> None:
    """ID-EMIS-LOGIN: an EMIS ID without an account raises the not-found error."""
    resolver = make_resolver(redis, accounts_with(), Ledger())

    with pytest.raises(EmisLoginNotFoundError):
        await resolver.execute(EMIS_ID, ctx=CTX)


async def test_blocked_account_looks_like_an_unregistered_id(redis: FakeRedis) -> None:
    """ID-EMIS-LOGIN: a blocked account gives the same answer as no account at all."""
    account = make_account(
        emis_student_id=int(EMIS_ID), status=UserStatus.BLOCKED, login="x.y"
    )
    resolver = make_resolver(redis, accounts_with(account), Ledger())

    with pytest.raises(EmisLoginNotFoundError):
        await resolver.execute(EMIS_ID, ctx=CTX)


async def test_sixth_attempt_from_one_ip_within_a_minute_is_rate_limited(
    redis: FakeRedis,
) -> None:
    """ID-EMIS-LOGIN: 5 lookups per minute per IP; the sixth is refused."""
    resolver = make_resolver(redis, accounts_with(), Ledger())
    for index in range(5):
        with pytest.raises(EmisLoginNotFoundError):
            await resolver.execute(str(78000 + index), ctx=CTX)

    with pytest.raises(RateLimitedError):
        await resolver.execute("79999", ctx=CTX)


async def test_twenty_first_attempt_from_one_ip_within_an_hour_is_rate_limited(
    redis: FakeRedis,
) -> None:
    """ID-EMIS-LOGIN: 20 lookups per hour per IP, spread over the minutes."""
    resolver = make_resolver(redis, accounts_with(), Ledger())
    for index in range(20):
        await _try_lookup(resolver, str(78000 + index))
        await redis.delete("rl:emis-login-ip-min:" + CTX.throttle_ip)

    with pytest.raises(RateLimitedError):
        await resolver.execute("79999", ctx=CTX)


async def test_lookups_do_not_count_against_an_emis_id(redis: FakeRedis) -> None:
    """ID-EMIS-LOGIN: only failed logins count per identifier; a lookup never blocks."""
    resolver = make_resolver(redis, accounts_with(), Ledger())
    for index in range(15):
        other = RequestContext(ip=f"198.51.100.{index + 1}", user_agent="pytest/1.0")
        await _try_lookup(resolver, EMIS_ID, ctx=other)

    with pytest.raises(EmisLoginNotFoundError):
        await resolver.execute(EMIS_ID, ctx=RequestContext(ip="192.0.2.9"))


async def test_ten_failed_logins_block_the_emis_id_whatever_the_ip(
    redis: FakeRedis,
) -> None:
    """ID-EMIS-LOGIN: 10 failed logins per hour for one identifier, any IP."""
    resolver = make_resolver(redis, accounts_with(), Ledger())
    for _ in range(10):
        await resolver.record_failure(EMIS_ID)

    with pytest.raises(RateLimitedError):
        await resolver.execute(EMIS_ID, ctx=RequestContext(ip="192.0.2.9"))


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "1234", "123456789012345", "78201a", "7820 1", "-78201", "7.8201"],
)
async def test_malformed_emis_id_is_rejected_before_any_lookup(
    redis: FakeRedis, raw: str
) -> None:
    """ID-EMIS-LOGIN: only 5 to 12 digits are an EMIS ID; anything else is invalid."""
    ledger = Ledger()
    resolver = make_resolver(redis, accounts_with(), ledger)

    with pytest.raises(EmisLoginInvalidError):
        await resolver.execute(raw, ctx=CTX)

    assert ledger.audits == []


async def test_surrounding_spaces_are_ignored(redis: FakeRedis) -> None:
    """ID-EMIS-LOGIN: a pasted ID with spaces around it still resolves."""
    account = make_account(emis_student_id=int(EMIS_ID), login="brastilov.aleksey")
    resolver = make_resolver(redis, accounts_with(account), Ledger())

    resolved = await resolver.execute(f"  {EMIS_ID} ", ctx=CTX)

    assert resolved.login == "brastilov.aleksey"


async def test_every_lookup_is_audited_with_a_masked_id(redis: FakeRedis) -> None:
    """ID-EMIS-LOGIN: the audit row keeps the outcome and only the last two digits."""
    account = make_account(emis_student_id=int(EMIS_ID), login="brastilov.aleksey")
    ledger = Ledger()
    resolver = make_resolver(redis, accounts_with(account), ledger)

    await resolver.execute(EMIS_ID, ctx=CTX)
    with pytest.raises(EmisLoginNotFoundError):
        await resolver.execute("90001", ctx=CTX)

    found, missing = ledger.audits
    assert found.type == EMIS_LOGIN_LOOKUP
    assert found.user_id == account.id
    assert found.metadata["emis_id"] == "***01"
    assert found.metadata["outcome"] == "found"
    assert missing.user_id is None
    assert missing.metadata["outcome"] == "not_found"
    assert EMIS_ID not in repr(ledger.audits)


async def test_rate_limited_attempt_is_audited(redis: FakeRedis) -> None:
    """ID-EMIS-LOGIN: refused attempts leave an audit row too."""
    ledger = Ledger()
    resolver = make_resolver(redis, accounts_with(), ledger)
    for index in range(5):
        await _try_lookup(resolver, str(78000 + index))

    with pytest.raises(RateLimitedError):
        await resolver.execute("79999", ctx=CTX)

    assert ledger.audits[-1].metadata["outcome"] == "rate_limited"


async def test_every_answer_waits_the_same_floor(redis: FakeRedis) -> None:
    """ID-EMIS-LOGIN: a found and a missing ID both take at least the floor time."""
    account = make_account(emis_student_id=int(EMIS_ID), login="brastilov.aleksey")
    recorder = Recorder()
    resolver = make_resolver(
        redis,
        accounts_with(account),
        Ledger(),
        floor_seconds=0.25,
        recorder=recorder,
    )

    await resolver.execute(EMIS_ID, ctx=CTX)
    with pytest.raises(EmisLoginNotFoundError):
        await resolver.execute("90001", ctx=CTX)

    assert recorder.pauses == [0.25, 0.25]


async def _try_lookup(
    resolver: ResolveEmisLogin, emis_id: str, ctx: RequestContext = CTX
) -> None:
    """Run one lookup that may end in not-found; any other error is a failure."""
    try:
        await resolver.execute(emis_id, ctx=ctx)
    except EmisLoginNotFoundError:
        return


async def test_registered_teacher_emis_id_resolves_to_the_teacher_login(
    redis: FakeRedis,
) -> None:
    """ID-EMIS-LOGIN: a teacher's EMIS teacher ID resolves when no student matches."""
    teachers = IdentityStore()
    teacher = make_user(
        emis_teacher_id=int(EMIS_ID), login="karimova.dilnoza", roles={Role.TEACHER}
    )
    teachers.users[teacher.id] = teacher
    resolver = make_resolver(redis, accounts_with(), Ledger(), teachers=teachers)

    resolved = await resolver.execute(EMIS_ID, ctx=CTX)

    assert resolved.login == "karimova.dilnoza"


async def test_inactive_teacher_emis_id_is_not_found(redis: FakeRedis) -> None:
    """ID-EMIS-LOGIN: a deactivated teacher is treated as unregistered."""
    teachers = IdentityStore()
    teacher = make_user(
        emis_teacher_id=int(EMIS_ID),
        login="karimova.dilnoza",
        roles={Role.TEACHER},
        status=UserStatus.DEACTIVATED,
    )
    teachers.users[teacher.id] = teacher
    resolver = make_resolver(redis, accounts_with(), Ledger(), teachers=teachers)

    with pytest.raises(EmisLoginNotFoundError):
        await resolver.execute(EMIS_ID, ctx=CTX)
