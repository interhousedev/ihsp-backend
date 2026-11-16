"""POST /v1/admin/users use case: invited accounts and one-time invitations."""

from typing import Any

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.telegram_onboarding import INVITE_PREFIX
from app.modules.identity.domain.errors import (
    EmailTakenError,
    InvitedRoleForbiddenError,
    InvitedRolesRequiredError,
)
from app.modules.identity.ports.init_data_verifier import InitDataUser
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.contracts.identity import AccountKind
from tests.identity.support import World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


@pytest.fixture
def world(auth_world: World) -> World:
    return auth_world


async def _create(world: World, actor: Actor, **over: Any) -> Any:
    args: dict[str, Any] = {
        "last_name": "Karimov",
        "first_name": "Ali",
        "middle_name": None,
        "account_kind": AccountKind.EXTERNAL,
        "roles": [Role.COUNSELOR],
        "email": None,
        "phone": "+998901234567",
        "ctx": CTX,
    }
    args.update(over)
    return await world.auth.create_invited_user.execute(actor, **args)


async def _admin(world: World) -> Actor:
    user = await world.add_user(roles={Role.ADMIN})
    return Actor(user_id=user.id, roles=frozenset({Role.ADMIN}))


@pytest.mark.parametrize("role", [Role.STUDENT, Role.TEACHER])
async def test_student_and_teacher_are_forbidden(world: World, role: Role) -> None:
    with pytest.raises(InvitedRoleForbiddenError):
        await _create(world, await _admin(world), roles=[role])


async def test_roles_required(world: World) -> None:
    with pytest.raises(InvitedRolesRequiredError):
        await _create(world, await _admin(world), roles=[])


async def test_admin_only(world: World) -> None:
    from app.shared.actor import Actor

    user = await world.add_user(roles={Role.TEACHER})
    with pytest.raises(ForbiddenError):
        await _create(world, Actor(user_id=user.id, roles=frozenset({Role.TEACHER})))


async def test_creates_user_with_kind_and_phone(world: World) -> None:
    created = await _create(
        world, await _admin(world), roles=[Role.MENTOR, Role.TRANSCRIPT_OFFICER]
    )
    assert created.user.account_kind is AccountKind.EXTERNAL
    assert created.user.phone == "+998901234567"
    assert set(created.user.roles) == {Role.MENTOR, Role.TRANSCRIPT_OFFICER}


async def test_duplicate_email(world: World) -> None:
    admin = await _admin(world)
    await _create(world, admin, email="a@example.com")
    with pytest.raises(EmailTakenError):
        await _create(world, admin, email="a@example.com")


async def test_invite_is_one_time(world: World) -> None:
    created = await _create(world, await _admin(world))
    assert f"start={INVITE_PREFIX}" in created.invite_url
    code = created.invite_url.split(f"start={INVITE_PREFIX}")[1]
    tg = InitDataUser(id=77, first_name="Ali")
    onboarding = world.auth.telegram_onboarding
    first = await onboarding.redeem_invite(code, tg)
    second = await onboarding.redeem_invite(code, tg)
    assert first.name == "LINKED"
    assert second.name == "EXPIRED"
