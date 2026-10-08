"""ID-9: destroying the Vault secret of a deleted account, also as a retried task."""

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import set_container
from app.interfaces.jobs.tasks.identity.destroy_emis_secret import destroy_emis_secret
from app.modules.identity.application.register_models import CredentialStoreError
from app.shared.contracts.identity import UserStatus
from tests.identity.emis.world import World

import pytest


async def deleted_student(world: World) -> tuple[UUID, UUID]:
    _, registered = await world.register()
    world.repo.accounts[registered.user_id].status = UserStatus.DELETED
    return registered.user_id, world.secret_ref_of(registered.user_id)


async def test_the_secret_and_its_reference_are_removed(world: World) -> None:
    """ID-9: all versions are destroyed, the row forgets the reference."""
    user_id, ref = await deleted_student(world)

    await world.destroy_emis_secret.execute(user_id)

    assert world.store.destroyed == [ref]
    assert world.repo.accounts[user_id].emis_vault_ref is None


async def test_a_live_account_is_never_destroyed(world: World) -> None:
    """ID-9: a stray task must not wipe the credentials of an active student."""
    _, registered = await world.register()

    await world.destroy_emis_secret.execute(registered.user_id)

    assert world.store.destroyed == []
    assert len(world.store.secrets) == 1


async def test_running_it_twice_is_harmless(world: World) -> None:
    """ID-9: the task is at-least-once."""
    user_id, _ = await deleted_student(world)

    await world.destroy_emis_secret.execute(user_id)
    await world.destroy_emis_secret.execute(user_id)

    assert len(world.store.destroyed) == 1


async def test_vault_errors_propagate_so_the_task_is_retried(world: World) -> None:
    """ID-9: the reference stays until the secret is really gone."""
    user_id, _ = await deleted_student(world)
    world.store.down = True

    with pytest.raises(CredentialStoreError):
        await world.destroy_emis_secret.execute(user_id)

    assert world.repo.accounts[user_id].emis_vault_ref is not None


async def test_the_task_is_registered_and_calls_the_use_case(world: World) -> None:
    """ID-9: ``identity.destroy_emis_secret`` finds the container's use case."""
    user_id, ref = await deleted_student(world)
    container = SimpleNamespace(
        identity=SimpleNamespace(
            emis=SimpleNamespace(destroy_emis_secret=world.destroy_emis_secret)
        )
    )
    set_container(cast(Any, container))

    await destroy_emis_secret(user_id)

    assert broker.find_task("identity.destroy_emis_secret") is not None
    assert world.store.destroyed == [ref]
