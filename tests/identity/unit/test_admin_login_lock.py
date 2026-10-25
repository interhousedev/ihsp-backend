"""Admin edits the login and the names; the locks and the EMIS sync respect them."""

from uuid import UUID

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import InvalidLoginError, LoginTakenError
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus
from tests.identity.support import World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


async def admin_of(world: World) -> Actor:
    """An Administration user and its actor."""
    admin = await world.add_user(
        roles={Role.ADMIN}, login="root.admin", recovery_email="root@example.org"
    )
    return Actor(user_id=admin.id, roles=frozenset({Role.ADMIN}))


def audit_of(world: World, user_id: UUID, event: str) -> list[dict]:
    """Metadata of the committed audit drafts of one type for one user."""
    return [
        a.metadata or {}
        for a in world.store.audits
        if a.type == event and a.user_id == user_id
    ]


async def test_admin_changes_login_and_names_with_audit_and_locks(
    auth_world: World,
) -> None:
    """The login is lowercased and locked; the audit holds old and new values."""
    admin = await admin_of(auth_world)
    student = await auth_world.add_user(
        login="karimova.dilnoza", last_name="Karimova", first_name="Dilnoza"
    )

    user = await auth_world.auth.update_user.execute(
        admin,
        student.id,
        last_name="Karimova",
        first_name="Dilnoza",
        middle_name=None,
        email=None,
        login="  Karimova.Dilnoza2 ",
        ctx=CTX,
    )

    assert user.login == "karimova.dilnoza2"
    assert user.login_locked is True
    assert user.name_locked is False  # the names did not change
    (audit,) = audit_of(auth_world, student.id, "user.updated")
    assert audit["changes"]["login"] == {
        "old": "karimova.dilnoza",
        "new": "karimova.dilnoza2",
    }
    assert "login" in audit["fields"]


async def test_changed_name_locks_the_names(auth_world: World) -> None:
    """A changed first name sets name_locked and audits the old and new value."""
    admin = await admin_of(auth_world)
    student = await auth_world.add_user(first_name="Dilnoza")

    user = await auth_world.auth.update_user.execute(
        admin,
        student.id,
        last_name=None,
        first_name="Dilnora",
        middle_name=None,
        email=None,
        ctx=CTX,
    )

    assert user.name_locked is True
    (audit,) = audit_of(auth_world, student.id, "user.updated")
    assert audit["changes"]["first_name"] == {"old": "Dilnoza", "new": "Dilnora"}


async def test_login_taken_case_insensitively_is_refused(auth_world: World) -> None:
    """Another account's login (any case) gives LoginTakenError; nothing changes."""
    admin = await admin_of(auth_world)
    await auth_world.add_user(login="aliev.bahodir")
    student = await auth_world.add_user(login="karimova.dilnoza")

    with pytest.raises(LoginTakenError):
        await auth_world.auth.update_user.execute(
            admin,
            student.id,
            last_name=None,
            first_name=None,
            middle_name=None,
            email=None,
            login="ALIEV.Bahodir",
            ctx=CTX,
        )

    assert auth_world.user(student.id).login == "karimova.dilnoza"


@pytest.mark.parametrize(
    "bad", ["ab", "Ivan Petrov", "ivan_p", "ивана", ".ivan", "a" * 101]
)
async def test_login_rules_are_enforced(auth_world: World, bad: str) -> None:
    """Login characters and length follow the base_login rules."""
    admin = await admin_of(auth_world)
    student = await auth_world.add_user(login="karimova.dilnoza")

    with pytest.raises(InvalidLoginError):
        await auth_world.auth.update_user.execute(
            admin,
            student.id,
            last_name=None,
            first_name=None,
            middle_name=None,
            email=None,
            login=bad,
            ctx=CTX,
        )


async def test_login_change_revokes_other_sessions_keeps_own(
    auth_world: World,
) -> None:
    """Like a password change: other devices log out; the admin's own session stays."""
    admin_user = await auth_world.add_user(roles={Role.ADMIN}, login="root.admin")
    admin = Actor(user_id=admin_user.id, roles=frozenset({Role.ADMIN}))
    own = auth_world.add_session(admin_user)
    student = await auth_world.add_user(login="karimova.dilnoza")
    device = auth_world.add_session(student)

    await auth_world.auth.update_user.execute(
        admin,
        student.id,
        last_name=None,
        first_name=None,
        middle_name=None,
        email=None,
        login="karimova.d",
        ctx=CTX,
    )
    admin_self = Actor(
        user_id=admin_user.id, roles=frozenset({Role.ADMIN}), session_id=own.id
    )
    await auth_world.auth.update_user.execute(
        admin_self,
        admin_user.id,
        last_name=None,
        first_name=None,
        middle_name=None,
        email=None,
        login="root.admin2",
        ctx=CTX,
    )

    assert auth_world.store.sessions[device.id].revoked_at is not None
    assert auth_world.store.sessions[own.id].revoked_at is None


async def test_emis_sync_skips_a_locked_name(auth_world: World) -> None:
    """update_names (the EMIS sync) keeps a name an administrator edited."""
    admin = await admin_of(auth_world)
    student = await auth_world.add_user(first_name="Dilnoza", last_name="Karimova")
    await auth_world.auth.update_user.execute(
        admin,
        student.id,
        last_name=None,
        first_name="Dilnora",
        middle_name=None,
        email=None,
        ctx=CTX,
    )

    await auth_world.auth.commands.update_names(
        student.id,
        first_name="Dilnoza",
        last_name="Karimova-Emis",
        middle_name=None,
    )

    user = auth_world.user(student.id)
    assert user.first_name == "Dilnora"
    assert user.last_name == "Karimova"
    assert user.status == UserStatus.ACTIVE


async def test_emis_sync_updates_an_unlocked_name(auth_world: World) -> None:
    """Without a manual edit the sync still writes the EMIS names."""
    student = await auth_world.add_user(first_name="Dilnoza", last_name="Karimova")

    await auth_world.auth.commands.update_names(
        student.id,
        first_name="Dilnoza",
        last_name="Karimova-Emis",
        middle_name=None,
    )

    assert auth_world.user(student.id).last_name == "Karimova-Emis"
