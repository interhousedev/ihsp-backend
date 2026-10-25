"""Passkeys: registration, sign-in, management and the password sign-in switch."""

import base64

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import (
    LastPasskeyError,
    PasskeyInvalidError,
    PasskeyNotFoundError,
    PasskeyRequiredError,
    PasswordLoginDisabledError,
)
from app.modules.identity.domain.user import User
from app.shared.actor import Actor, Role
from tests.fakes.identity.webauthn import FakeWebAuthn, credential
from tests.identity.support import PASSWORD, World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


def actor_of(user: User) -> Actor:
    """The signed-in user."""
    return Actor(user_id=user.id, roles=frozenset(user.roles))


def fake(world: World) -> FakeWebAuthn:
    """The scripted relying party."""
    assert isinstance(world.webauthn, FakeWebAuthn)
    return world.webauthn


async def register(world: World, user: User, raw_id: bytes = b"cred-1"):
    """Options, then the browser's answer."""
    manage = world.auth.factors.manage_passkeys
    await manage.registration_options(actor_of(user))
    return await manage.register(
        actor_of(user), credential(fake(world), raw_id), "MacBook", CTX
    )


async def test_register_stores_the_credential(auth_world: World) -> None:
    """Credential id, public key, sign count, transports, name, created at."""
    user = await auth_world.add_user()

    passkey = await register(auth_world, user)

    stored = auth_world.store.passkeys[passkey.id]
    assert stored.credential_id == b"cred-1"
    assert stored.public_key == b"pk-cred-1"
    assert stored.name == "MacBook" and stored.transports == ["internal"]
    assert stored.created_at == auth_world.clock.now()
    assert "passkey.added" in auth_world.store.audit_types(user.id)


async def test_existing_passkeys_are_excluded_and_a_replay_fails(
    auth_world: World,
) -> None:
    """The options exclude known credentials; options are single use."""
    user = await auth_world.add_user()
    await register(auth_world, user)
    manage = auth_world.auth.factors.manage_passkeys

    await manage.registration_options(actor_of(user))
    assert fake(auth_world).excluded == [b"cred-1"]
    answer = credential(fake(auth_world), b"cred-2")
    await manage.register(actor_of(user), answer, "Phone", CTX)
    with pytest.raises(PasskeyInvalidError):
        await manage.register(actor_of(user), answer, "Phone", CTX)


async def test_a_wrong_challenge_is_refused(auth_world: World) -> None:
    """Verification failures raise PasskeyInvalidError."""
    user = await auth_world.add_user()
    manage = auth_world.auth.factors.manage_passkeys
    await manage.registration_options(actor_of(user))
    answer = credential(fake(auth_world), b"cred-1", challenge="other")

    with pytest.raises(PasskeyInvalidError):
        await manage.register(actor_of(user), answer, "x", CTX)
    assert auth_world.store.passkeys == {}


async def test_sign_in_with_a_passkey_accepts_the_hydra_login(
    auth_world: World,
) -> None:
    """amr hwk, mfa; sign count and last use are updated."""
    user = await auth_world.add_user()
    passkey = await register(auth_world, user)
    auth_world.hydra.add_login("lc-1")
    login = auth_world.auth.factors.log_in_with_passkey

    options = await login.options("lc-1", CTX)
    assert options["challenge"]
    answer = credential(
        fake(auth_world), b"cred-1", response={"userHandle": _b64(user.id.bytes)}
    )
    result = await login.execute("lc-1", answer, remember=True, ctx=CTX)

    assert result.redirect_to
    accepted = auth_world.hydra.last("accept_login")
    assert accepted["subject"] == str(user.id) and accepted["amr"] == ["hwk"]
    stored = auth_world.store.passkeys[passkey.id]
    assert stored.sign_count == 1 and stored.last_used_at == auth_world.clock.now()


async def test_unknown_credential_or_other_user_handle_fails(
    auth_world: World,
) -> None:
    """The credential must exist and belong to the user handle it claims."""
    user = await auth_world.add_user()
    other = await auth_world.add_user(login="other.user")
    await register(auth_world, user)
    auth_world.hydra.add_login("lc-1")
    login = auth_world.auth.factors.log_in_with_passkey

    await login.options("lc-1", CTX)
    with pytest.raises(PasskeyInvalidError):
        await login.execute(
            "lc-1", credential(fake(auth_world), b"nope"), remember=False, ctx=CTX
        )
    await login.options("lc-1", CTX)
    forged = credential(
        fake(auth_world), b"cred-1", response={"userHandle": _b64(other.id.bytes)}
    )
    with pytest.raises(PasskeyInvalidError):
        await login.execute("lc-1", forged, remember=False, ctx=CTX)


async def test_rename_and_delete_only_own_passkeys(auth_world: World) -> None:
    """Another user's passkey is not found."""
    user = await auth_world.add_user()
    other = await auth_world.add_user(login="other.user")
    passkey = await register(auth_world, user)
    manage = auth_world.auth.factors.manage_passkeys

    renamed = await manage.rename(actor_of(user), passkey.id, "  Work laptop ")
    assert renamed.name == "Work laptop"
    with pytest.raises(PasskeyNotFoundError):
        await manage.delete(actor_of(other), passkey.id, CTX)
    await manage.delete(actor_of(user), passkey.id, CTX)
    assert auth_world.store.passkeys == {}


async def test_password_off_needs_a_passkey_and_keeps_the_last_one(
    auth_world: World,
) -> None:
    """Off only with a passkey; the last passkey stays; password login refused."""
    user = await auth_world.add_user()
    manage = auth_world.auth.factors.manage_passkeys
    with pytest.raises(PasskeyRequiredError):
        await manage.disable_password_login(actor_of(user), CTX)

    first = await register(auth_world, user, b"cred-1")
    second = await register(auth_world, user, b"cred-2")
    await manage.disable_password_login(actor_of(user), CTX)
    overview = await manage.overview(actor_of(user))
    assert not overview.password_login_enabled and len(overview.passkeys) == 2

    await manage.delete(actor_of(user), first.id, CTX)
    with pytest.raises(LastPasskeyError):
        await manage.delete(actor_of(user), second.id, CTX)

    auth_world.hydra.add_login("lc-1")
    with pytest.raises(PasswordLoginDisabledError):
        await auth_world.auth.log_in_with_password.execute(
            "lc-1", user.login or "", PASSWORD, remember=False, ctx=CTX
        )


async def test_admin_setting_a_password_turns_password_login_back_on(
    auth_world: World,
) -> None:
    """A new password re-enables password sign-in."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, login="the.admin")
    user = await auth_world.add_user()
    await register(auth_world, user)
    await auth_world.auth.factors.manage_passkeys.disable_password_login(
        actor_of(user), CTX
    )

    await auth_world.auth.admin_set_password.execute(
        actor_of(admin), user.id, "N3wStrongPass", require_change=False, ctx=CTX
    )

    assert not auth_world.store.factors[user.id].password_login_disabled


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")
