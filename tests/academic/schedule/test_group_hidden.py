"""Admins hide a group: it leaves lists and curator pickers, the data stays."""

from app.modules.academic.domain.schedule.errors import GroupNotFoundError
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.academic.schedule.env import Env
from tests.factories import make_actor

import pytest


async def test_a_hidden_group_leaves_the_default_list(env: Env) -> None:
    """A hidden group is skipped unless the caller asks for it."""
    shown = await env.group("2TN1")
    hidden = await env.group("2TN2")
    admin = make_actor(Role.ADMIN)

    detail = await env.services.update_group.execute(admin, hidden.id, hidden=True)

    assert detail.hidden is True
    default = await env.services.list_groups.execute(None)
    assert [g.id for g in default] == [shown.id]
    everything = await env.services.list_groups.execute(None, include_hidden=True)
    assert {g.id: g.hidden for g in everything} == {shown.id: False, hidden.id: True}


async def test_unhiding_brings_the_group_back_with_its_data(env: Env) -> None:
    """Hiding keeps the group and its curator."""
    curator = env.teacher()
    group = await env.group("2TN2", curator=curator)
    admin = make_actor(Role.ADMIN)
    await env.services.update_group.execute(admin, group.id, hidden=True)

    detail = await env.services.update_group.execute(admin, group.id, hidden=False)

    assert detail.hidden is False and detail.curator is not None
    assert [g.id for g in await env.services.list_groups.execute(None)] == [group.id]


async def test_a_hidden_group_is_not_in_the_curators_groups(env: Env) -> None:
    """The curator's picker skips a hidden group."""
    curator = env.teacher()
    group = await env.group("2TN2", curator=curator)
    admin = make_actor(Role.ADMIN)
    await env.services.update_group.execute(admin, group.id, hidden=True)

    async with env.uow_factory() as uow:
        assert await uow.groups.curated_by(curator.id) == []


async def test_hiding_an_unknown_group_is_not_found(env: Env) -> None:
    """The group must exist."""
    with pytest.raises(GroupNotFoundError):
        await env.services.update_group.execute(
            make_actor(Role.ADMIN), new_id(), hidden=True
        )
