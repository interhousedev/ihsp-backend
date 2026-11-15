"""Telegram bot registry over HTTP (Administration only), with in-memory fakes."""

from types import SimpleNamespace

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_bots import router
from app.modules.admin.application.bot_admin import BotAdmin
from app.modules.identity.domain.errors import StepUpInvalidError
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admin.unit.test_bot_admin import (
    ENV_TOKEN,
    TOKEN_A,
    TOKEN_A2,
    TOKEN_B,
    MemoryVault,
    Probe,
)
from tests.admin.unit.test_broadcasts import Admin
from tests.conftest import HttpClientFactory
from tests.fakes.clock import FixedClock

import pytest
from httpx import AsyncClient

GOOD_CODE = "123456"


class FakeStepUp:
    """Accepts one code, like ``StepUp.verify``."""

    async def verify(self, actor: Actor, code: str) -> None:
        """The real invalid-code error unless the code is the right one."""
        if code != GOOD_CODE:
            raise StepUpInvalidError()


IDENTITY = SimpleNamespace(auth=SimpleNamespace(step_up=FakeStepUp()))


def services(bots: BotAdmin) -> SimpleNamespace:
    """Admin services with the bot registry and an idle maintenance gate."""
    idle = SimpleNamespace(info=lambda: SimpleNamespace(active=False))
    return SimpleNamespace(bot_admin=bots, migration=idle)


@pytest.fixture
def adm(clock: FixedClock) -> Admin:
    return Admin(clock)


@pytest.fixture
def bots(adm: Admin, clock: FixedClock) -> BotAdmin:
    return BotAdmin(
        uow_factory=adm.world.uow,
        vault=MemoryVault(),
        probe=Probe(),
        resolver=adm.resolver,
        clock=clock,
        step_up=FakeStepUp().verify,
    )


@pytest.fixture
async def client(
    adm: Admin, bots: BotAdmin, http_client: HttpClientFactory
) -> AsyncClient:
    return await http_client(
        [router],
        overrides={get_actor: lambda: adm.actor},
        admin=services(bots),
        identity=IDENTITY,
    )


async def test_add_list_patch_and_rotate(client: AsyncClient, bots: BotAdmin) -> None:
    await bots.import_default_bot(ENV_TOKEN, "ihspbot")

    created = await client.post(
        "/v1/admin/bots",
        json={"name": "Extra", "token": TOKEN_A, "otp_code": GOOD_CODE},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["token_mask"] == "…" + TOKEN_A[-4:]
    assert "token" not in body
    assert body["features"]["announcements"] is False

    listed = (await client.get("/v1/admin/bots")).json()["items"]
    assert [b["is_default"] for b in listed] == [True, False]
    assert all(listed[0]["features"].values())

    patched = await client.patch(
        f"/v1/admin/bots/{body['id']}",
        json={
            "features": {"announcements": True},
            "name": "News",
            "otp_code": GOOD_CODE,
        },
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "News"
    assert patched.json()["features"]["announcements"] is True

    rotated = await client.post(
        f"/v1/admin/bots/{body['id']}/rotate-token",
        json={"token": "111111:" + "Z" * 32 + "9876", "otp_code": GOOD_CODE},
    )
    assert rotated.json()["token_mask"] == "…9876"


async def test_errors_are_problem_json(client: AsyncClient, bots: BotAdmin) -> None:
    default = await bots.import_default_bot(ENV_TOKEN, "ihspbot")
    assert default is not None

    bad = await client.post(
        "/v1/admin/bots",
        json={"name": "x", "token": "nope:" + "a" * 20, "otp_code": GOOD_CODE},
    )
    assert bad.status_code in (400, 422)
    assert bad.headers["content-type"].startswith("application/problem+json")
    locked = await client.patch(
        f"/v1/admin/bots/{default.id}", json={"enabled": False, "otp_code": GOOD_CODE}
    )
    assert locked.status_code == 409
    unknown = await client.patch(
        f"/v1/admin/bots/{default.id}",
        json={"features": {"teleport": True}, "otp_code": GOOD_CODE},
    )
    rotated = await client.post(
        f"/v1/admin/bots/{default.id}/rotate-token",
        json={"token": "999999:" + "Z" * 36, "otp_code": GOOD_CODE},
    )
    assert rotated.status_code == 409
    assert rotated.json()["type"].endswith("admin/bot-default-token-env")
    assert unknown.status_code == 422
    missing = await client.patch(
        f"/v1/admin/bots/{new_id()}", json={"enabled": True, "otp_code": GOOD_CODE}
    )
    assert missing.status_code == 404


async def test_announce_reports_per_bot(
    adm: Admin, client: AsyncClient, bots: BotAdmin
) -> None:
    adm.students(2)
    default = await bots.import_default_bot(ENV_TOKEN, "ihspbot")
    assert default is not None
    draft = await adm.draft()

    response = await client.post(
        "/v1/admin/bots/announcements",
        json={
            "broadcast_id": str(draft.broadcast.id),
            "bot_ids": [str(default.id)],
            "otp_code": GOOD_CODE,
        },
    )

    assert response.status_code == 200
    assert response.json()["recipients"] == 2
    assert response.json()["per_bot"] == {str(default.id): 2}


async def test_writes_need_a_valid_step_up_code(
    adm: Admin, client: AsyncClient, bots: BotAdmin
) -> None:
    default = await bots.import_default_bot(ENV_TOKEN, "ihspbot")
    assert default is not None
    extra = await bots.add(adm.actor, name="Extra", token=TOKEN_A, otp_code=GOOD_CODE)
    wrong = {"otp_code": "000000"}

    added = await client.post(
        "/v1/admin/bots", json={"name": "Other", "token": TOKEN_B, **wrong}
    )
    rotated = await client.post(
        f"/v1/admin/bots/{extra.bot.id}/rotate-token",
        json={"token": TOKEN_A2, **wrong},
    )
    announced = await client.post(
        "/v1/admin/bots/announcements",
        json={"broadcast_id": str(new_id()), "bot_ids": [str(default.id)], **wrong},
    )
    patched = await client.patch(
        f"/v1/admin/bots/{default.id}", json={"name": "Renamed", **wrong}
    )
    invalid = await client.patch(
        f"/v1/admin/bots/{default.id}", json={"features": {"teleport": True}, **wrong}
    )
    missing = await client.post(
        "/v1/admin/bots", json={"name": "Extra", "token": TOKEN_A}
    )
    unconfirmed = await client.patch(
        f"/v1/admin/bots/{default.id}", json={"name": "Renamed"}
    )

    for response in (added, rotated, announced, patched):
        assert response.status_code == 403
        assert response.json()["type"].endswith("identity/step-up-invalid")
    assert invalid.status_code == 422
    assert invalid.json()["type"].endswith("admin/bot-feature-unknown")
    assert missing.status_code == 422
    assert unconfirmed.status_code == 422
    items = (await client.get("/v1/admin/bots")).json()["items"]
    assert [(b["name"], b["token_mask"]) for b in items] == [
        (default.name, "…" + ENV_TOKEN[-4:]),
        ("Extra", "…" + TOKEN_A[-4:]),
    ]


async def test_only_admins_reach_the_registry(
    adm: Admin, bots: BotAdmin, http_client: HttpClientFactory
) -> None:
    teacher = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))
    client = await http_client(
        [router], overrides={get_actor: lambda: teacher}, admin=services(bots)
    )
    assert (await client.get("/v1/admin/bots")).status_code == 403
