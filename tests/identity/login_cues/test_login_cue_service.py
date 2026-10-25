"""Login cues: masking, consumed cues, the public picker and its rate limit."""

import asyncio
import json
from dataclasses import asdict, fields
from datetime import UTC, datetime
from uuid import UUID

from app.modules.identity.application.login_cues import (
    LoginCueGroupNotFoundError,
    LoginCueService,
    LoginCueUnavailableError,
    NewLoginCue,
)
from app.modules.identity.domain.login_cue import short_names
from app.shared.base_error import RateLimitedError
from app.shared.contracts.emis import EmisAuthFailed
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter
from tests.fakes.clock import FixedClock
from tests.fakes.identity.login_cues import (
    FakeCueGroups,
    InMemoryLoginCueRepository,
    StubStart,
)
from tests.fakes.identity.vault import InMemoryCredentialStore

import pytest
from fakeredis.aioredis import FakeRedis

LOGIN = "20240123456"
GROUP = new_id()
OTHER_GROUP = new_id()


class Harness:
    """A login cue service over in-memory fakes."""

    def __init__(self, redis: FakeRedis) -> None:
        self.repo = InMemoryLoginCueRepository()
        self.store = InMemoryCredentialStore()
        self.groups = FakeCueGroups({GROUP: "10-A", OTHER_GROUP: "11-B"})
        self.start = StubStart()
        self.clock = FixedClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC))
        self.service = LoginCueService(
            repository=self.repo,
            store=self.store,
            groups=self.groups,
            start=self.start,
            rate_limiter=RateLimiter(redis),
            clock=self.clock,
        )


@pytest.fixture
def harness(redis: FakeRedis) -> Harness:
    return Harness(redis)


async def _add(
    h: Harness, login: str = LOGIN, name: str = "Valiyev Ali Akramovich"
) -> UUID:
    (view,) = await h.service.create(
        [NewLoginCue(emis_login=login, full_name=name, group_id=GROUP)]
    )
    return view.id


async def test_admin_view_masks_login_to_last_two_characters(harness: Harness) -> None:
    (view,) = await harness.service.create(
        [NewLoginCue(emis_login=LOGIN, full_name="Ali", group_id=GROUP)]
    )
    assert view.login_masked == "••••" + LOGIN[-2:]
    listed = await harness.service.list_for_admin()
    assert [c.login_masked for c in listed] == ["••••" + LOGIN[-2:]]
    assert LOGIN not in json.dumps([asdict(c) for c in listed], default=str)
    assert view.group_name == "10-A"


async def test_stored_login_is_encrypted(harness: Harness) -> None:
    cue_id = await _add(harness)
    stored = harness.repo.cues[cue_id].emis_login_enc
    assert LOGIN not in stored
    assert await harness.store.decrypt(stored) == LOGIN


async def test_create_rejects_unknown_group(harness: Harness) -> None:
    with pytest.raises(LoginCueGroupNotFoundError):
        await harness.service.create(
            [NewLoginCue(emis_login=LOGIN, full_name="Ali", group_id=new_id())]
        )
    assert harness.repo.cues == {}


async def test_bulk_is_all_or_nothing(harness: Harness) -> None:
    with pytest.raises(LoginCueGroupNotFoundError):
        await harness.service.create(
            [
                NewLoginCue(emis_login="1", full_name="A", group_id=GROUP),
                NewLoginCue(emis_login="2", full_name="B", group_id=new_id()),
            ]
        )
    assert harness.repo.cues == {}


async def test_public_picker_exposes_only_opaque_id_and_name(
    harness: Harness,
) -> None:
    cue_id = await _add(harness)
    options = await harness.service.cues_of_group(GROUP, ip="1.1.1.1")
    payload = json.dumps(
        [{"cue_id": str(o.cue_id), "display_name": o.display_name} for o in options]
    )
    assert options[0].cue_id == cue_id
    assert LOGIN not in payload
    assert {f.name for f in fields(options[0])} == {"cue_id", "display_name"}


async def test_groups_list_only_groups_with_open_cues(harness: Harness) -> None:
    await _add(harness)
    groups = await harness.service.groups_with_cues(ip="1.1.1.1")
    assert [(g.group_id, g.name) for g in groups] == [(GROUP, "10-A")]


async def test_start_uses_server_side_login_and_claims_once(harness: Harness) -> None:
    cue_id = await _add(harness)
    await harness.service.start_registration(
        cue_id=cue_id, emis_password="pw", ip=None, locale="ru"
    )
    assert harness.start.logins == [LOGIN]
    assert harness.repo.cues[cue_id].consumed
    with pytest.raises(LoginCueUnavailableError):
        await harness.service.start_registration(
            cue_id=cue_id, emis_password="pw", ip=None, locale="ru"
        )
    assert harness.start.logins == [LOGIN]
    assert await harness.service.cues_of_group(GROUP, ip=None) == []


async def test_failed_emis_check_does_not_consume_cue(harness: Harness) -> None:
    class Failing(StubStart):
        async def execute(self, **kwargs: object) -> object:
            raise ValueError("wrong EMIS password")

    harness.service._start = Failing()  # noqa: SLF001 - swap the collaborator
    cue_id = await _add(harness)
    with pytest.raises(ValueError):
        await harness.service.start_registration(
            cue_id=cue_id, emis_password="bad", ip=None, locale="ru"
        )
    assert not harness.repo.cues[cue_id].consumed


async def test_unknown_cue_is_unavailable(harness: Harness) -> None:
    with pytest.raises(LoginCueUnavailableError):
        await harness.service.start_registration(
            cue_id=new_id(), emis_password="pw", ip=None, locale="ru"
        )


async def test_public_listing_is_rate_limited_per_ip(harness: Harness) -> None:
    for _ in range(30):
        await harness.service.groups_with_cues(ip="2.2.2.2")
    with pytest.raises(RateLimitedError):
        await harness.service.groups_with_cues(ip="2.2.2.2")
    # another address has its own budget
    await harness.service.groups_with_cues(ip="3.3.3.3")


class WrongPasswordStart(StubStart):
    """EMIS rejects the password of every call."""

    async def execute(self, **kwargs: object) -> object:
        raise EmisAuthFailed(support_details="wrong password")


class FailingStart(StubStart):
    """A failure that is not a wrong password (EMIS unavailable, say)."""

    async def execute(self, **kwargs: object) -> object:
        raise ValueError("EMIS unavailable")


class GatedStart(StubStart):
    """Holds the first call open until the test releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()

    async def execute(self, **kwargs: object) -> object:
        self.logins.append(str(kwargs["emis_login"]))
        await self.gate.wait()
        return object()


async def test_five_wrong_passwords_block_the_cue_for_the_hour(
    harness: Harness,
) -> None:
    cue_id = await _add(harness)
    harness.service._start = WrongPasswordStart()  # noqa: SLF001
    for _ in range(5):
        with pytest.raises(EmisAuthFailed):
            await harness.service.start_registration(
                cue_id=cue_id, emis_password="bad", ip=None, locale="ru"
            )
    good = StubStart()
    harness.service._start = good  # noqa: SLF001
    with pytest.raises(RateLimitedError):
        await harness.service.start_registration(
            cue_id=cue_id, emis_password="right", ip=None, locale="ru"
        )
    assert good.logins == []
    assert not harness.repo.cues[cue_id].consumed


async def test_the_block_is_per_cue(harness: Harness) -> None:
    blocked = await _add(harness, login="20240000001")
    other = await _add(harness, login="20240000002")
    harness.service._start = WrongPasswordStart()  # noqa: SLF001
    for _ in range(5):
        with pytest.raises(EmisAuthFailed):
            await harness.service.start_registration(
                cue_id=blocked, emis_password="bad", ip=None, locale="ru"
            )
    harness.service._start = StubStart()  # noqa: SLF001
    await harness.service.start_registration(
        cue_id=other, emis_password="right", ip=None, locale="ru"
    )
    assert harness.repo.cues[other].consumed


async def test_failures_that_are_not_wrong_passwords_are_not_counted(
    harness: Harness,
) -> None:
    cue_id = await _add(harness)
    harness.service._start = FailingStart()  # noqa: SLF001
    for _ in range(6):
        with pytest.raises(ValueError):
            await harness.service.start_registration(
                cue_id=cue_id, emis_password="pw", ip=None, locale="ru"
            )
    harness.service._start = StubStart()  # noqa: SLF001
    await harness.service.start_registration(
        cue_id=cue_id, emis_password="pw", ip=None, locale="ru"
    )
    assert harness.repo.cues[cue_id].consumed


async def test_concurrent_claims_start_registration_once(harness: Harness) -> None:
    cue_id = await _add(harness)
    gated = GatedStart()
    harness.service._start = gated  # noqa: SLF001

    first = asyncio.create_task(
        harness.service.start_registration(
            cue_id=cue_id, emis_password="pw", ip=None, locale="ru"
        )
    )
    await asyncio.sleep(0)
    with pytest.raises(LoginCueUnavailableError):
        await harness.service.start_registration(
            cue_id=cue_id, emis_password="pw", ip=None, locale="ru"
        )
    gated.gate.set()
    await first

    assert gated.logins == [LOGIN]
    assert harness.repo.cues[cue_id].consumed


async def test_failed_start_releases_the_reservation(harness: Harness) -> None:
    cue_id = await _add(harness)
    harness.service._start = FailingStart()  # noqa: SLF001
    with pytest.raises(ValueError):
        await harness.service.start_registration(
            cue_id=cue_id, emis_password="pw", ip=None, locale="ru"
        )
    assert cue_id not in harness.repo.reserved
    harness.service._start = StubStart()  # noqa: SLF001
    await harness.service.start_registration(
        cue_id=cue_id, emis_password="pw", ip=None, locale="ru"
    )
    assert harness.repo.cues[cue_id].consumed


async def test_delete_unknown_cue_raises(harness: Harness) -> None:
    from app.modules.identity.application.login_cues import LoginCueNotFoundError

    with pytest.raises(LoginCueNotFoundError):
        await harness.service.delete(new_id())


def test_public_names_are_given_names_only() -> None:
    """Login cues: a public list shows given names only; repeats are numbered."""
    names = short_names(
        [
            "Valiyev Ali Akramovich",
            "Karimova Dilnoza Botirovna",
            "Karimova Dilnoza Aliyevna",
        ]
    )

    assert names == ["Ali", "Dilnoza (1)", "Dilnoza (2)"]
