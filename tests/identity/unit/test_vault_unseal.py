"""Vault unseal: admin only, rate limit, key never leaks."""

import dataclasses
import logging

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import (
    VaultKeyRejectedError,
    VaultUnavailableError,
)
from app.modules.identity.domain.user import User
from app.modules.identity.infrastructure.http_vault_seal import HttpVaultSeal
from app.settings import VaultSettings
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError, RateLimitedError
from tests.fakes.identity.vault_seal import FakeVaultSeal
from tests.identity.support import World

import httpx
import pytest
from pydantic import SecretStr

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")
KEY = SecretStr("s3cr3t-unseal-key-share-AAAA")


def actor_of(user: User) -> Actor:
    """The caller."""
    return Actor(user_id=user.id, roles=frozenset(user.roles))


async def with_fake(world: World) -> FakeVaultSeal:
    """Point both use cases at a fake seal."""
    fake = FakeVaultSeal()
    world.auth.unseal_vault = dataclasses.replace(world.auth.unseal_vault, seal=fake)
    world.auth.get_vault_status = dataclasses.replace(
        world.auth.get_vault_status, seal=fake
    )
    return fake


async def test_unseal_forwards_the_key_and_audits_without_it(
    auth_world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """The key reaches Vault only; logs, audit and repr never hold it."""
    caplog.set_level(logging.DEBUG)
    fake = await with_fake(auth_world)
    admin = await auth_world.add_user(roles={Role.ADMIN})

    state = await auth_world.auth.unseal_vault.execute(
        actor_of(admin), key=KEY, ctx=CTX
    )

    assert fake.received == [KEY.get_secret_value()]
    assert state.progress == 1 and state.sealed
    assert "vault.unseal_submitted" in auth_world.store.audit_types(admin.id)
    secret = KEY.get_secret_value()
    assert secret not in repr(auth_world.store.audits)
    assert secret not in caplog.text
    assert secret not in repr(KEY)


async def test_unseal_needs_no_code(auth_world: World) -> None:
    """An administrator with a key and no code gets the share submitted."""
    fake = await with_fake(auth_world)
    admin = await auth_world.add_user(roles={Role.ADMIN})
    await auth_world.auth.unseal_vault.execute(actor_of(admin), key=KEY, ctx=CTX)
    assert fake.received == [KEY.get_secret_value()]


async def test_only_administrators_may_use_it(auth_world: World) -> None:
    """Students get 403 for both calls."""
    await with_fake(auth_world)
    user = await auth_world.add_user()
    with pytest.raises(ForbiddenError):
        await auth_world.auth.get_vault_status.execute(actor_of(user))
    with pytest.raises(ForbiddenError):
        await auth_world.auth.unseal_vault.execute(actor_of(user), key=KEY, ctx=CTX)


async def test_status_reports_the_seal(auth_world: World) -> None:
    """Status mirrors the port."""
    await with_fake(auth_world)
    admin = await auth_world.add_user(roles={Role.ADMIN})
    state = await auth_world.auth.get_vault_status.execute(actor_of(admin))
    assert (state.sealed, state.progress, state.threshold, state.shares) == (
        True,
        0,
        3,
        5,
    )


async def test_attempts_are_rate_limited(auth_world: World) -> None:
    """Too many tries in a window raise RateLimitedError."""
    await with_fake(auth_world)
    admin = await auth_world.add_user(roles={Role.ADMIN})
    with pytest.raises(RateLimitedError):
        for _ in range(50):
            await auth_world.auth.unseal_vault.execute(
                actor_of(admin), key=KEY, ctx=CTX
            )


async def test_vault_errors_pass_through(auth_world: World) -> None:
    """The use case does not swallow the port's errors."""
    fake = await with_fake(auth_world)
    admin = await auth_world.add_user(roles={Role.ADMIN})
    for error in (VaultUnavailableError(), VaultKeyRejectedError()):
        fake.error = error
        with pytest.raises(type(error)):
            await auth_world.auth.unseal_vault.execute(
                actor_of(admin), key=KEY, ctx=CTX
            )


async def test_http_adapter_maps_vault_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """seal-status fields, 400 -> key rejected, 5xx and network -> unavailable."""
    answers: list[httpx.Response | Exception] = []

    def handler(request: httpx.Request) -> httpx.Response:
        item = answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    seal = HttpVaultSeal(VaultSettings(url="http://vault:8200"))

    answers.append(
        httpx.Response(200, json={"sealed": True, "t": 3, "n": 5, "progress": 2})
    )
    state = await seal.status()
    assert (state.sealed, state.progress, state.threshold, state.shares) == (
        True,
        2,
        3,
        5,
    )

    answers.append(httpx.Response(400, json={"errors": ["bad key"]}))
    with pytest.raises(VaultKeyRejectedError):
        await seal.submit_key(KEY)
    answers.append(httpx.Response(503))
    with pytest.raises(VaultUnavailableError):
        await seal.status()
    answers.append(httpx.ConnectError("boom"))
    with pytest.raises(VaultUnavailableError):
        await seal.submit_key(KEY)
