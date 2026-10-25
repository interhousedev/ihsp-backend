"""Admin edits a user, sets an initial password; the optional forced change at login."""

from typing import Any

from app.modules.identity.application.login_result import LoginResult
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.update_user import UserNameEmptyError
from app.modules.identity.domain.errors import (
    AdminResetForbiddenError,
    EmailTakenError,
    InvalidCredentialsError,
    PasswordPolicyError,
)
from app.modules.identity.domain.user import User
from app.settings import Settings
from app.settings_features import FeaturesSettings
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus
from app.shared.i18n.core import I18nCore
from tests.identity.build_world import build_world
from tests.identity.support import PASSWORD, World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")
NEW = "Brand-New-1"


async def admin_of(world: World) -> Actor:
    """An Administration user and its actor."""
    admin = await world.add_user(
        roles={Role.ADMIN}, login="root.admin", recovery_email="root@example.org"
    )
    return Actor(user_id=admin.id, roles=frozenset({Role.ADMIN}))


async def teacher_from_emis(world: World, **fields: Any) -> User:
    """A teacher account as the EMIS sync creates it: pending, no email, no password."""
    return await world.add_user(
        roles={Role.TEACHER},
        status=UserStatus.PENDING_ACTIVATION,
        login="aliev.bahodir",
        password_hash=None,
        recovery_email=None,
        **fields,
    )


def world_with_flag(
    auth_world: World, settings: Settings, i18n: I18nCore, enabled: bool
) -> World:
    """A second world whose settings have the change-password feature set."""
    changed = settings.model_copy(
        update={"features": FeaturesSettings(change_password_on_login=enabled)}
    )
    return build_world(
        changed, i18n, auth_world.redis, auth_world.clock, auth_world.kicker
    )


# - - - Edit name and email - - -


async def test_admin_edits_name_and_email_of_any_user(auth_world: World) -> None:
    """Names are trimmed, the email lowered; user.updated and email.changed audited."""
    admin = await admin_of(auth_world)
    student = await auth_world.add_user(
        recovery_email="old@example.org",
        recovery_email_verified_at=auth_world.clock.now(),
    )

    user = await auth_world.auth.update_user.execute(
        admin,
        student.id,
        last_name=" Karimova ",
        first_name="Dilnoza",
        middle_name="",
        email="New@Example.org",
        ctx=CTX,
    )

    assert (user.last_name, user.first_name, user.middle_name) == (
        "Karimova",
        "Dilnoza",
        None,
    )
    assert user.recovery_email == "new@example.org"
    assert user.recovery_email_verified_at == auth_world.clock.now()
    audit = auth_world.store.audit_types(student.id)
    assert "user.updated" in audit
    assert "email.changed" in audit


async def test_nothing_changed_writes_no_audit(auth_world: World) -> None:
    """Sending the same values is a no-op."""
    admin = await admin_of(auth_world)
    student = await auth_world.add_user(recovery_email="same@example.org")

    await auth_world.auth.update_user.execute(
        admin,
        student.id,
        last_name=student.last_name,
        first_name=None,
        middle_name=None,
        email="Same@example.org",
        ctx=CTX,
    )

    assert "user.updated" not in auth_world.store.audit_types(student.id)


async def test_an_email_of_another_account_is_refused(auth_world: World) -> None:
    """Uniqueness is case-insensitive."""
    admin = await admin_of(auth_world)
    await auth_world.add_user(recovery_email="taken@example.org")
    student = await auth_world.add_user(recovery_email="mine@example.org")

    with pytest.raises(EmailTakenError):
        await auth_world.auth.update_user.execute(
            admin,
            student.id,
            last_name=None,
            first_name=None,
            middle_name=None,
            email="TAKEN@example.org",
            ctx=CTX,
        )

    assert auth_world.user(student.id).recovery_email == "mine@example.org"


async def test_a_blank_name_is_refused(auth_world: World) -> None:
    """A name cannot be cleared."""
    admin = await admin_of(auth_world)
    student = await auth_world.add_user()

    with pytest.raises(UserNameEmptyError):
        await auth_world.auth.update_user.execute(
            admin,
            student.id,
            last_name="   ",
            first_name=None,
            middle_name=None,
            email=None,
            ctx=CTX,
        )


async def test_a_pending_account_gets_an_activation_link_for_a_new_email(
    auth_world: World,
) -> None:
    """The teacher EMIS created has no email; adding one sends the link."""
    admin = await admin_of(auth_world)
    teacher = await teacher_from_emis(auth_world)

    user = await auth_world.auth.update_user.execute(
        admin,
        teacher.id,
        last_name=None,
        first_name=None,
        middle_name=None,
        email="aliev@example.org",
        ctx=CTX,
    )

    assert user.recovery_email_verified_at is None
    assert auth_world.email.to("aliev@example.org", "activation")


# - - - Initial password - - -


async def test_admin_sets_the_initial_password_of_an_emis_teacher(
    auth_world: World,
) -> None:
    """The pending account becomes active and the teacher can sign in."""
    admin = await admin_of(auth_world)
    teacher = await teacher_from_emis(auth_world)
    auth_world.hydra.add_login("lc-1", client_id="lms")

    await auth_world.auth.admin_set_password.execute(
        admin, teacher.id, NEW, require_change=True, ctx=CTX
    )

    user = auth_world.user(teacher.id)
    assert user.status == UserStatus.ACTIVE
    assert user.password_change_required is True
    audit = auth_world.store.audit_types(teacher.id)
    assert "password.reset_by_admin" in audit
    assert "user.activated" in audit
    result = await auth_world.auth.log_in_with_password.execute(
        "lc-1", "aliev.bahodir", NEW, remember=False, ctx=CTX
    )
    assert result.redirect_to is not None
    assert result.password_change is None


async def test_a_weak_password_and_self_service_are_refused(auth_world: World) -> None:
    """The policy applies; an admin cannot set their own password this way."""
    admin = await admin_of(auth_world)
    teacher = await teacher_from_emis(auth_world)

    with pytest.raises(PasswordPolicyError):
        await auth_world.auth.admin_set_password.execute(
            admin, teacher.id, "weak", require_change=False, ctx=CTX
        )
    with pytest.raises(AdminResetForbiddenError):
        await auth_world.auth.admin_set_password.execute(
            admin, admin.user_id, NEW, require_change=False, ctx=CTX
        )


# - - - change_password_on_login flag - - -


async def _set_and_login(world: World) -> tuple[User, LoginResult]:
    admin = await admin_of(world)
    teacher = await teacher_from_emis(world)
    world.hydra.add_login("lc-1", client_id="lms")
    await world.auth.admin_set_password.execute(
        admin, teacher.id, NEW, require_change=True, ctx=CTX
    )
    result = await world.auth.log_in_with_password.execute(
        "lc-1", "aliev.bahodir", NEW, remember=False, ctx=CTX
    )
    return teacher, result


async def test_flag_off_an_admin_set_password_signs_in_directly(
    auth_world: World,
) -> None:
    """Default: no change step."""
    _, result = await _set_and_login(auth_world)

    assert result.redirect_to is not None
    assert result.password_change is None


async def test_flag_on_the_user_must_change_the_password_first(
    auth_world: World, settings: Settings, i18n: I18nCore
) -> None:
    """A ticket instead of a redirect; the new password finishes the login."""
    world = world_with_flag(auth_world, settings, i18n, True)
    teacher, result = await _set_and_login(world)

    assert result.redirect_to is None
    assert result.password_change is not None

    with pytest.raises(PasswordPolicyError):
        await world.auth.log_in_with_new_password.execute(
            "lc-1", result.password_change.ticket, NEW, ctx=CTX
        )
    with pytest.raises(PasswordPolicyError):
        await world.auth.log_in_with_new_password.execute(
            "lc-1", result.password_change.ticket, "weak", ctx=CTX
        )
    done = await world.auth.log_in_with_new_password.execute(
        "lc-1", result.password_change.ticket, "Second-Pass-2", ctx=CTX
    )

    assert done.redirect_to is not None
    assert world.user(teacher.id).password_change_required is False
    assert "password.changed" in world.store.audit_types(teacher.id)
    with pytest.raises(InvalidCredentialsError):
        await world.auth.log_in_with_new_password.execute(
            "lc-1", result.password_change.ticket, "Third-Pass-3", ctx=CTX
        )


async def test_flag_on_a_normal_password_is_not_asked_to_change(
    auth_world: World, settings: Settings, i18n: I18nCore
) -> None:
    """Only admin-set passwords are marked."""
    world = world_with_flag(auth_world, settings, i18n, True)
    user = await world.add_user()
    world.hydra.add_login("lc-1")

    result = await world.auth.log_in_with_password.execute(
        "lc-1", user.login, PASSWORD, remember=False, ctx=CTX
    )

    assert result.redirect_to is not None


async def test_the_ticket_is_bound_to_its_challenge(
    auth_world: World, settings: Settings, i18n: I18nCore
) -> None:
    """A ticket from one login cannot finish another."""
    world = world_with_flag(auth_world, settings, i18n, True)
    _, result = await _set_and_login(world)
    assert result.password_change is not None

    with pytest.raises(InvalidCredentialsError):
        await world.auth.log_in_with_new_password.execute(
            "other", result.password_change.ticket, "Second-Pass-2", ctx=CTX
        )
