"""Contracts IdentityDirectory and IdentityCommands, and the clean-up job."""

from datetime import timedelta

from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError
from app.shared.contracts.identity import UserPreferences, UserStatus
from app.shared.ids import new_id
from tests.identity.support import World

import pytest


async def test_directory_finds_users_by_id_login_and_telegram(
    auth_world: World,
) -> None:
    """Contract: get_user, get_users, user_by_login (active only), user_by_telegram."""
    active = await auth_world.add_user()
    blocked = await auth_world.add_user(
        login="b.locked", status=UserStatus.BLOCKED, recovery_email="b@example.org"
    )
    auth_world.add_link(active, 555)
    directory = auth_world.auth.directory

    ref = await directory.get_user(active.id)
    assert ref is not None and ref.login == active.login
    assert ref.roles == frozenset({Role.STUDENT}) and ref.locale == "ru"
    assert await directory.get_user(new_id()) is None
    assert set(await directory.get_users([active.id, blocked.id, new_id()])) == {
        active.id,
        blocked.id,
    }
    assert (await directory.user_by_login(active.login.upper())).id == active.id
    assert await directory.user_by_login(blocked.login) is None
    assert (await directory.user_by_telegram(555)).id == active.id
    assert await directory.user_by_telegram(1) is None


async def test_directory_preferences_fill_in_defaults(auth_world: World) -> None:
    """Contract: get_preferences returns every key."""
    user = await auth_world.add_user(preferences={"locale": "uz"})

    prefs = await auth_world.auth.directory.get_preferences(user.id)

    assert prefs.locale == "uz" and prefs.marks_values == [2, 3, 4, 5]
    assert (
        await auth_world.auth.directory.get_preferences(new_id()) == UserPreferences()
    )


async def test_directory_searches_and_lists_roles(auth_world: World) -> None:
    """Contract: search_users and user_ids_with_roles see active users only."""
    teacher = await auth_world.add_user(
        roles={Role.TEACHER},
        login="kal.gav",
        first_name="Gavxar",
        last_name="Kalandarova",
        recovery_email="k@example.org",
    )
    await auth_world.add_user(
        login="gone.user",
        status=UserStatus.DEACTIVATED,
        roles={Role.TEACHER},
        recovery_email="g@example.org",
    )
    directory = auth_world.auth.directory

    found = await directory.search_users("kalandarova gavxar", roles=[Role.TEACHER])
    assert [u.id for u in found] == [teacher.id]
    assert await directory.search_users("kalandarova", roles=[Role.ADMIN]) == []
    assert await directory.user_ids_with_roles([Role.TEACHER]) == [teacher.id]


async def test_telegram_accounts_and_the_blocked_flag(auth_world: World) -> None:
    """BOT-22: blocking the bot marks the link; writing again clears it."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)
    directory = auth_world.auth.directory

    await directory.set_telegram_blocked(555, True)
    (account,) = await directory.telegram_accounts(user.id)
    assert (account.telegram_user_id, account.blocked, account.otp_delivery) == (
        555,
        True,
        True,
    )

    await directory.set_telegram_blocked(555, False)
    (account,) = await directory.telegram_accounts(user.id)
    assert account.blocked is False
    await directory.set_telegram_blocked(1, True)  # unknown account: ignored


async def test_touch_telegram_refreshes_name_and_username(auth_world: World) -> None:
    """ID-21: the cached username follows Telegram."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555, username="old")
    auth_world.clock.advance(hours=1)

    await auth_world.auth.directory.touch_telegram(555, "new", "Newname")

    link = auth_world.store.links[555]
    assert (link.username, link.first_name, link.last_seen_at) == (
        "new",
        "Newname",
        auth_world.clock.now(),
    )


async def test_commands_create_an_unregistered_student(auth_world: World) -> None:
    """ACA-18: imported students have no login yet."""
    ref = await auth_world.auth.commands.create_unregistered_student(
        first_name="Aleksey",
        last_name="Brastilov",
        middle_name=None,
        emis_student_id=78218,
    )

    stored = auth_world.user(ref.id)
    assert (stored.status, stored.login, stored.roles, stored.emis_student_id) == (
        UserStatus.UNREGISTERED,
        None,
        {Role.STUDENT},
        78218,
    )


async def test_commands_update_names_and_emis_status(auth_world: World) -> None:
    """SYNC-4, SYNC-8: names from EMIS and the needs_reauth flag."""
    user = await auth_world.add_user()
    commands = auth_world.auth.commands

    await commands.update_names(
        user.id, first_name="Ali", last_name="B", middle_name="M"
    )
    await commands.set_emis_status(user.id, "needs_reauth")

    stored = auth_world.user(user.id)
    assert (stored.first_name, stored.last_name, stored.middle_name) == (
        "Ali",
        "B",
        "M",
    )
    assert stored.emis_status == "needs_reauth"


async def test_commands_update_preferences_validates(auth_world: World) -> None:
    """Contract: update_preferences merges and returns the result."""
    user = await auth_world.add_user()

    prefs = await auth_world.auth.commands.update_preferences(
        user.id, {"seen_marks_at": "2026-10-06T09:00:00Z", "alerts_drops": False}
    )
    assert prefs.alerts_drops is False and prefs.seen_marks_at is not None
    with pytest.raises(ValidationFailedError):
        await auth_world.auth.commands.update_preferences(user.id, {"locale": "xx"})


async def test_commands_unlink_telegram(auth_world: World) -> None:
    """BOT-7: the bot's Log out button."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)

    await auth_world.auth.commands.unlink_telegram(555)
    await auth_world.auth.commands.unlink_telegram(555)  # idempotent

    assert auth_world.store.links == {}
    assert auth_world.store.audit_types(user.id) == ["telegram.unlinked"]


async def test_close_account_revokes_everything_and_starts_the_clean_up(
    auth_world: World,
) -> None:
    """ID-29: status deleted, access revoked, files, links and Vault clean-up kicked."""
    user = await auth_world.add_user(auth_epoch=1)
    session = auth_world.add_session(user)
    auth_world.add_link(user, 555)

    await auth_world.auth.commands.close_account(user.id, reason="student request")

    stored = auth_world.user(user.id)
    assert stored.status == UserStatus.DELETED
    assert stored.deleted_at == auth_world.clock.now()
    assert stored.auth_epoch > 1
    assert auth_world.store.sessions[session.id].revoked_at is not None
    assert auth_world.store.links == {}
    assert auth_world.kicker.names() == [
        "identity.destroy_emis_secret",
        "files.delete_owner",
        "links.revoke_owner",
    ]
    assert all(kw == {"user_id": str(user.id)} for _, kw in auth_world.kicker.calls)


async def test_purge_anonymizes_accounts_deleted_30_days_ago(auth_world: World) -> None:
    """ID-29: personal data goes after 30 days; the row stays for the records."""
    user = await auth_world.add_user(
        preferences={"locale": "uz"}, emis_student_id=78218, otp_enabled=True
    )
    await auth_world.auth.commands.close_account(user.id, reason="x")

    assert await auth_world.auth.purge_deleted_users.execute() == 0
    auth_world.clock.advance(days=31)
    assert await auth_world.auth.purge_deleted_users.execute() == 1
    assert await auth_world.auth.purge_deleted_users.execute() == 0  # not twice

    stored = auth_world.user(user.id)
    assert (stored.first_name, stored.last_name, stored.middle_name) == (
        "Deleted",
        "",
        None,
    )
    assert stored.login == f"deleted-{user.id.hex[-12:]}"
    assert stored.recovery_email is None and stored.password_hash is None
    assert stored.preferences == {} and stored.emis_student_id is None
    assert stored.status == UserStatus.DELETED
    assert stored.deleted_at is not None
    assert timedelta(days=30) < auth_world.clock.now() - stored.deleted_at
