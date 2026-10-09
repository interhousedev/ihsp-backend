"""ADM-4, ADM-5, ID-10, ID-11, GEN-5: staff accounts and user administration."""

from datetime import timedelta

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import (
    ActivationLinkInvalidError,
    AdminResetForbiddenError,
    CourseCreatorNotStaffError,
    EmailLockedError,
    EmailTakenError,
    InvalidStatusError,
    LmsAdminNeedsAdminError,
    OtpInvalidError,
    PasswordPolicyError,
    SelfActionForbiddenError,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError, ValidationFailedError
from app.shared.contracts.identity import UserStatus
from app.shared.ids import hash_token
from tests.identity.support import World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


async def admin_of(world: World) -> Actor:
    """An Administration user and its actor."""
    admin = await world.add_user(
        roles={Role.ADMIN},
        otp_enabled=True,
        login="root.admin",
        recovery_email="root@example.org",
    )
    return Actor(user_id=admin.id, roles=frozenset({Role.ADMIN}))


def token_of(url: str) -> str:
    """The token inside an activation URL."""
    return url.split("token=")[1]


# - - - Teacher accounts - - -


async def test_creating_a_teacher_generates_the_login_and_a_72_hour_link(
    auth_world: World,
) -> None:
    """ID-10, UF-ADM-02: login surname.name, pending activation, emailed link."""
    admin = await admin_of(auth_world)

    created = await auth_world.auth.create_teacher.execute(
        admin.user_id,
        last_name="Kalandarova",
        first_name="Gavxar",
        middle_name=None,
        email="Teacher@Example.org",
        ctx=CTX,
    )

    user = auth_world.user(created.user.id)
    assert user.login == "kalandarova.gavxar"
    assert user.roles == {Role.TEACHER}
    assert user.status == UserStatus.PENDING_ACTIVATION
    assert user.recovery_email == "teacher@example.org"
    assert user.activation_expires_at == auth_world.clock.now() + timedelta(hours=72)
    assert user.activation_token_hash == hash_token(token_of(created.activation_url))
    assert created.activation_url.startswith("http://localhost:3001/activate/?token=")
    (mail,) = auth_world.email.to("teacher@example.org", "activation")
    assert mail["link"] == created.activation_url
    assert mail["hours"] == 72
    assert "user.created" in auth_world.store.audit_types(user.id)


async def test_same_name_gets_a_numbered_login(auth_world: World) -> None:
    """ID-5: collisions append a number."""
    admin = await admin_of(auth_world)

    first = await auth_world.auth.create_teacher.execute(
        admin.user_id,
        last_name="Kalandarova",
        first_name="Gavxar",
        middle_name=None,
        email="a@example.org",
        ctx=CTX,
    )
    second = await auth_world.auth.create_teacher.execute(
        admin.user_id,
        last_name="KALANDAROVA",
        first_name="Gavxar",
        middle_name=None,
        email="b@example.org",
        ctx=CTX,
    )

    assert (first.user.login, second.user.login) == (
        "kalandarova.gavxar",
        "kalandarova.gavxar2",
    )


async def test_cyrillic_names_are_transliterated_into_the_login(
    auth_world: World,
) -> None:
    """ID-5: lowercase Latin."""
    admin = await admin_of(auth_world)

    created = await auth_world.auth.create_teacher.execute(
        admin.user_id,
        last_name="Каландарова",
        first_name="Гавхар",
        middle_name=None,
        email="c@example.org",
        ctx=CTX,
    )

    assert created.user.login == "kalandarova.gavxar"


async def test_teacher_email_must_be_unique(auth_world: World) -> None:
    """ID-4: one recovery email per account."""
    admin = await admin_of(auth_world)
    await auth_world.add_user(login="x.y", recovery_email="taken@example.org")

    with pytest.raises(EmailTakenError):
        await auth_world.auth.create_teacher.execute(
            admin.user_id,
            last_name="A",
            first_name="B",
            middle_name=None,
            email="TAKEN@example.org",
            ctx=CTX,
        )


async def test_a_broken_mail_relay_does_not_lose_the_link(auth_world: World) -> None:
    """UF-ADM-02 3: the link is still shown for the admin to pass on."""
    admin = await admin_of(auth_world)
    auth_world.email.fail = True

    created = await auth_world.auth.create_teacher.execute(
        admin.user_id,
        last_name="A",
        first_name="B",
        middle_name=None,
        email="a@example.org",
        ctx=CTX,
    )

    assert created.activation_url


# - - - Activation - - -


async def activation_link(world: World, email: str = "t@example.org") -> str:
    """Create a teacher and return its token."""
    admin = await admin_of(world)
    created = await world.auth.create_teacher.execute(
        admin.user_id,
        last_name="Kalandarova",
        first_name="Gavxar",
        middle_name=None,
        email=email,
        ctx=CTX,
    )
    return token_of(created.activation_url)


async def test_activation_page_shows_name_and_login(auth_world: World) -> None:
    """UF-ID-13 2."""
    token = await activation_link(auth_world)

    info = await auth_world.auth.activation_info.execute(token)

    assert (info.first_name, info.last_name, info.login, info.requires_otp) == (
        "Gavxar",
        "Kalandarova",
        "kalandarova.gavxar",
        False,
    )


async def test_teacher_activates_with_a_password_and_a_confirmed_email(
    auth_world: World,
) -> None:
    """UF-ID-13: password rules, email confirmed with a code, redirect to staff."""
    token = await activation_link(auth_world)

    await auth_world.auth.activation_send_email_code.execute(
        token, "me@example.org", CTX
    )
    code = auth_world.email.last_code("me@example.org")
    redirect = await auth_world.auth.activate_account.execute(
        token,
        password="N3wStrongPass",
        email="me@example.org",
        email_code=code,
        ctx=CTX,
    )

    assert redirect == "http://localhost:3003"
    user = next(
        u for u in auth_world.store.users.values() if u.login == "kalandarova.gavxar"
    )
    assert user.status == UserStatus.ACTIVE
    assert user.recovery_email == "me@example.org"
    assert user.recovery_email_verified_at == auth_world.clock.now()
    assert user.activation_token_hash is None
    assert await auth_world.auth.hasher.verify(user.password_hash, "N3wStrongPass")
    with pytest.raises(ActivationLinkInvalidError):
        await auth_world.auth.activation_info.execute(token)


async def test_activation_with_a_wrong_code_or_other_email_fails(
    auth_world: World,
) -> None:
    """UF-ID-13 3: the code must belong to the address."""
    token = await activation_link(auth_world)
    await auth_world.auth.activation_send_email_code.execute(
        token, "me@example.org", CTX
    )
    code = auth_world.email.last_code("me@example.org")

    with pytest.raises(OtpInvalidError):
        await auth_world.auth.activate_account.execute(
            token,
            password="N3wStrongPass",
            email="other@example.org",
            email_code=code,
            ctx=CTX,
        )
    with pytest.raises(PasswordPolicyError):
        await auth_world.auth.activate_account.execute(
            token, password="weak", email="me@example.org", email_code=code, ctx=CTX
        )
    with pytest.raises(ValidationFailedError):
        await auth_world.auth.activate_account.execute(
            token, password="N3wStrongPass", email=None, email_code=None, ctx=CTX
        )


async def test_expired_activation_link_is_gone(auth_world: World) -> None:
    """UF-ID-13 2a: valid 72 hours."""
    token = await activation_link(auth_world)
    auth_world.clock.advance(hours=73)

    with pytest.raises(ActivationLinkInvalidError) as caught:
        await auth_world.auth.activation_info.execute(token)

    assert caught.value.status == 410


async def test_unknown_activation_token_is_gone(auth_world: World) -> None:
    """A guessed token never works."""
    with pytest.raises(ActivationLinkInvalidError):
        await auth_world.auth.activation_info.execute("nope")


async def test_administration_activation_turns_on_email_otp_and_redirects_to_admin(
    auth_world: World,
) -> None:
    """ID-11, UF-ID-13 4: the confirmed email is the first OTP channel."""
    root = await admin_of(auth_world)
    created = await auth_world.auth.create_staff_account.execute(
        actor_id=root.user_id,
        last_name="Boss",
        first_name="Big",
        middle_name=None,
        email="boss@example.org",
        roles=[Role.ADMIN],
        ctx=CTX,
    )
    token = token_of(created.activation_url)
    info = await auth_world.auth.activation_info.execute(token)
    assert info.requires_otp is True

    await auth_world.auth.activation_send_email_code.execute(
        token, "boss@example.org", CTX
    )
    redirect = await auth_world.auth.activate_account.execute(
        token,
        password="N3wStrongPass",
        email="boss@example.org",
        email_code=auth_world.email.last_code("boss@example.org"),
        ctx=CTX,
    )

    boss = auth_world.user(created.user.id)
    assert redirect == "http://localhost:3004"
    assert (boss.otp_enabled, boss.otp_via_email) == (True, True)
    auth_world.hydra.add_login("lc-1", client_id="admin")
    first = await auth_world.auth.log_in_with_password.execute(
        "lc-1", boss.login or "", "N3wStrongPass", remember=False, ctx=CTX
    )
    assert first.second_factor is not None
    assert first.second_factor.channels == ["email"]


# - - - Block, roles, sessions - - -


async def test_blocking_logs_the_user_out_everywhere(auth_world: World) -> None:
    """GEN-5, UF-ADM-11: epoch bump, sessions and connectors revoked, links kept."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user(auth_epoch=2)
    session = auth_world.add_session(user)
    connector = auth_world.add_connector(user)
    auth_world.add_link(user, 555)

    result = await auth_world.auth.block_user.execute(admin, user.id, "spam", CTX)

    assert result.status == UserStatus.BLOCKED
    stored = auth_world.user(user.id)
    assert stored.auth_epoch > 2
    assert auth_world.store.sessions[session.id].revoked_at is not None
    assert auth_world.store.connectors[connector.id].revoked_at is not None
    assert 555 in auth_world.store.links
    assert await auth_world.redis.exists(f"auth:revoked:{session.id}")
    assert await auth_world.redis.exists(f"auth:revoked:{connector.id}")
    assert await auth_world.redis.get(f"auth:epoch:{user.id}") == str(stored.auth_epoch)
    names = auth_world.hydra.names()
    assert "revoke_login_sessions" in names and "revoke_consent_sessions" in names
    event = next(e for e in auth_world.store.events if e.type == "user.blocked")
    assert (event.user_id, event.actor_id, event.metadata) == (
        user.id,
        admin.user_id,
        {"reason": "spam"},
    )


async def test_administrator_cannot_block_themselves(auth_world: World) -> None:
    """A safeguard against locking everyone out."""
    admin = await admin_of(auth_world)

    with pytest.raises(SelfActionForbiddenError):
        await auth_world.auth.block_user.execute(admin, admin.user_id, "oops", CTX)


async def test_unblocking_restores_the_account_but_not_the_sessions(
    auth_world: World,
) -> None:
    """UF-ADM-11 2: sessions have to be created again."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user()
    session = auth_world.add_session(user)
    await auth_world.auth.block_user.execute(admin, user.id, "x", CTX)

    result = await auth_world.auth.unblock_user.execute(admin, user.id, CTX)

    assert result.status == UserStatus.ACTIVE
    assert auth_world.store.sessions[session.id].revoked_at is not None
    with pytest.raises(InvalidStatusError):
        await auth_world.auth.unblock_user.execute(admin, user.id, CTX)


async def test_role_change_bumps_the_epoch_and_revokes_hydra_sessions(
    auth_world: World,
) -> None:
    """ID-11: any role change logs the user out everywhere."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user(auth_epoch=5)
    session = auth_world.add_session(user)

    result = await auth_world.auth.change_roles.execute(
        admin, user.id, grant=[Role.ADMIN], revoke=[], ctx=CTX
    )

    assert Role.ADMIN in result.roles
    stored = auth_world.user(user.id)
    assert stored.auth_epoch > 5
    assert stored.otp_enabled is True  # OTP is mandatory for Administration
    assert auth_world.store.sessions[session.id].revoked_at is not None
    assert auth_world.hydra.last("revoke_login_sessions")["subject"] == str(user.id)
    assert auth_world.hydra.last("revoke_consent_sessions")["subject"] == str(user.id)
    assert auth_world.store.audit_types(user.id).count("role.granted") == 1


async def test_revoking_a_role_is_audited_and_unchanged_roles_do_nothing(
    auth_world: World,
) -> None:
    """ADM-5: grants and revokes are audit events; no-ops leave sessions alone."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user(roles={Role.STUDENT, Role.LMS_ADMIN})
    session = auth_world.add_session(user)

    await auth_world.auth.change_roles.execute(
        admin, user.id, grant=[], revoke=[Role.LIBRARIAN], ctx=CTX
    )
    assert auth_world.store.sessions[session.id].revoked_at is None
    assert auth_world.store.audits == []

    await auth_world.auth.change_roles.execute(
        admin, user.id, grant=[], revoke=[Role.LMS_ADMIN], ctx=CTX
    )
    assert auth_world.user(user.id).roles == {Role.STUDENT}
    assert auth_world.store.audit_types(user.id) == ["role.revoked"]


async def test_only_administration_roles_can_be_managed_and_not_your_own(
    auth_world: World,
) -> None:
    """ADM-5: the Administration and LMS admin roles; no self-demotion."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user()

    with pytest.raises(ValidationFailedError):
        await auth_world.auth.change_roles.execute(
            admin, user.id, grant=[Role.TEACHER], revoke=[], ctx=CTX
        )
    with pytest.raises(SelfActionForbiddenError):
        await auth_world.auth.change_roles.execute(
            admin, admin.user_id, grant=[], revoke=[Role.ADMIN], ctx=CTX
        )


async def test_librarian_can_be_granted_to_a_student_and_a_teacher(
    auth_world: World,
) -> None:
    """ADM-5, LIB-1: `librarian` joins other roles and writes a library audit event."""
    admin = await admin_of(auth_world)
    student = await auth_world.add_user(roles={Role.STUDENT})
    teacher = await auth_world.add_user(roles={Role.TEACHER}, login="t.lib")

    for user in (student, teacher):
        await auth_world.auth.change_roles.execute(
            admin, user.id, grant=[Role.LIBRARIAN], revoke=[], ctx=CTX
        )

    assert auth_world.user(student.id).roles == {Role.STUDENT, Role.LIBRARIAN}
    assert auth_world.user(teacher.id).roles == {Role.TEACHER, Role.LIBRARIAN}
    assert auth_world.store.audit_types(student.id) == [
        "role.granted",
        "library.role_granted",
    ]


async def test_revoking_librarian_is_a_plain_role_revoke(auth_world: World) -> None:
    """ADM-5, LIB-1: only the grant writes `library.role_granted`."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user(roles={Role.STUDENT, Role.LIBRARIAN})

    await auth_world.auth.change_roles.execute(
        admin, user.id, grant=[], revoke=[Role.LIBRARIAN], ctx=CTX
    )

    assert auth_world.user(user.id).roles == {Role.STUDENT}
    assert auth_world.store.audit_types(user.id) == ["role.revoked"]


async def test_the_librarian_grant_event_names_the_role_and_the_admin(
    auth_world: World,
) -> None:
    """GEN-6, LIB-1: the library audit event carries the role and who granted it."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user(roles={Role.STUDENT})

    await auth_world.auth.change_roles.execute(
        admin, user.id, grant=[Role.LIBRARIAN], revoke=[], ctx=CTX
    )

    event = next(a for a in auth_world.store.audits if a.type == "library.role_granted")
    assert event.user_id == user.id
    assert event.actor_id == admin.user_id
    assert event.metadata == {"role": "librarian"}


async def test_lms_admin_is_granted_only_to_a_member_of_administration(
    auth_world: World,
) -> None:
    """ADM-5: `lms_admin` rides on `admin`: refused for others, fine together."""
    admin = await admin_of(auth_world)
    teacher = await auth_world.add_user(roles={Role.TEACHER}, login="t.plain")
    member = await auth_world.add_user(roles={Role.ADMIN}, login="a.member")
    fresh = await auth_world.add_user(roles={Role.TEACHER}, login="t.fresh")

    for user in (teacher, fresh):
        with pytest.raises(LmsAdminNeedsAdminError):
            await auth_world.auth.change_roles.execute(
                admin, user.id, grant=[Role.LMS_ADMIN], revoke=[], ctx=CTX
            )
    with pytest.raises(LmsAdminNeedsAdminError):
        await auth_world.auth.change_roles.execute(
            admin,
            member.id,
            grant=[Role.LMS_ADMIN],
            revoke=[Role.ADMIN],
            ctx=CTX,
        )
    await auth_world.auth.change_roles.execute(
        admin, member.id, grant=[Role.LMS_ADMIN], revoke=[], ctx=CTX
    )
    await auth_world.auth.change_roles.execute(
        admin, fresh.id, grant=[Role.ADMIN, Role.LMS_ADMIN], revoke=[], ctx=CTX
    )

    assert auth_world.user(teacher.id).roles == {Role.TEACHER}
    assert auth_world.user(member.id).roles == {Role.ADMIN, Role.LMS_ADMIN}
    assert auth_world.user(fresh.id).roles == {
        Role.TEACHER,
        Role.ADMIN,
        Role.LMS_ADMIN,
    }


async def test_removing_admin_removes_lms_admin_too(auth_world: World) -> None:
    """ADM-5: both revocations are audited; keeping `admin` keeps nothing extra."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user(
        roles={Role.TEACHER, Role.ADMIN, Role.LMS_ADMIN}, login="t.both"
    )

    await auth_world.auth.change_roles.execute(
        admin, user.id, grant=[], revoke=[Role.ADMIN], ctx=CTX
    )

    assert auth_world.user(user.id).roles == {Role.TEACHER}
    revoked = [a for a in auth_world.store.audits if a.type == "role.revoked"]
    assert sorted((a.metadata or {})["role"] for a in revoked) == [
        "admin",
        "lms_admin",
    ]


async def test_revoking_lms_admin_alone_keeps_admin(auth_world: World) -> None:
    """ADM-5: the dependency only goes one way."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user(
        roles={Role.ADMIN, Role.LMS_ADMIN}, login="a.keeps"
    )

    await auth_world.auth.change_roles.execute(
        admin, user.id, grant=[], revoke=[Role.LMS_ADMIN], ctx=CTX
    )

    assert auth_world.user(user.id).roles == {Role.ADMIN}


async def test_course_creator_is_granted_to_teachers_and_admins_only(
    auth_world: World,
) -> None:
    """ADM-5: a student cannot be a course creator; the grant is audited."""
    admin = await admin_of(auth_world)
    student = await auth_world.add_user(roles={Role.STUDENT}, login="s.no")
    teacher = await auth_world.add_user(roles={Role.TEACHER}, login="t.yes")

    with pytest.raises(CourseCreatorNotStaffError):
        await auth_world.auth.change_roles.execute(
            admin, student.id, grant=[Role.LMS_CREATOR], revoke=[], ctx=CTX
        )
    await auth_world.auth.change_roles.execute(
        admin, teacher.id, grant=[Role.LMS_CREATOR], revoke=[], ctx=CTX
    )

    assert auth_world.user(student.id).roles == {Role.STUDENT}
    assert auth_world.user(teacher.id).roles == {Role.TEACHER, Role.LMS_CREATOR}
    event = next(a for a in auth_world.store.audits if a.type == "role.granted")
    assert event.user_id == teacher.id
    assert event.actor_id == admin.user_id
    assert event.metadata == {"role": "lms_creator"}


async def test_revoking_sessions_does_not_touch_the_epoch(auth_world: World) -> None:
    """ADM-5: only sessions are cut; tokens die through the revocation list."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user(auth_epoch=3)
    sessions = [auth_world.add_session(user) for _ in range(2)]

    count = await auth_world.auth.revoke_user_sessions.execute(admin, user.id, CTX)

    assert count == 2
    assert auth_world.user(user.id).auth_epoch == 3
    assert all(auth_world.store.sessions[s.id].revoked_at for s in sessions)


# - - - Reset password / OTP, mail - - -


async def test_admin_reset_password_returns_a_link_and_emails_it(
    auth_world: World,
) -> None:
    """ADM-5: a reset link with purpose reset_password."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user(auth_epoch=1)
    session = auth_world.add_session(user)

    url = await auth_world.auth.admin_reset_password.execute(admin, user.id, CTX)

    assert auth_world.user(user.id).activation_purpose.value == "reset_password"
    assert auth_world.email.to(user.recovery_email or "", "activation")
    # The old password keeps working until the link is used.
    assert auth_world.store.sessions[session.id].revoked_at is None

    await auth_world.auth.activate_account.execute(
        token_of(url), password="N3wStrongPass", email=None, email_code=None, ctx=CTX
    )

    assert auth_world.store.sessions[session.id].revoked_at is not None
    assert await auth_world.auth.hasher.verify(
        auth_world.user(user.id).password_hash, "N3wStrongPass"
    )


async def test_an_administrator_cannot_reset_their_own_password_or_otp(
    auth_world: World,
) -> None:
    """ID-23: the email of an Administration account cannot reset it."""
    admin = await admin_of(auth_world)

    with pytest.raises(AdminResetForbiddenError):
        await auth_world.auth.admin_reset_password.execute(admin, admin.user_id, CTX)
    with pytest.raises(AdminResetForbiddenError):
        await auth_world.auth.admin_reset_otp.execute(admin, admin.user_id, CTX)


async def test_another_administrator_can_reset_the_otp(auth_world: World) -> None:
    """UF-ADM-11 4: Telegram links go, OTP stays on."""
    admin = await admin_of(auth_world)
    other = await auth_world.add_user(
        roles={Role.ADMIN},
        otp_enabled=True,
        login="other.admin",
        recovery_email="oa@example.org",
    )
    auth_world.add_link(other, 777)

    await auth_world.auth.admin_reset_otp.execute(admin, other.id, CTX)

    stored = auth_world.user(other.id)
    assert auth_world.store.links == {}
    assert stored.otp_enabled is True
    assert stored.otp_via_email is True


async def test_mail_can_be_suspended_and_resumed(auth_world: World) -> None:
    """MAIL-8, UF-ADM-15: suspension notifies the user."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user()

    suspended = await auth_world.auth.suspend_mail.execute(admin, user.id, "spam", CTX)
    assert suspended.mail_suspended_at == auth_world.clock.now()
    assert auth_world.store.notification_types() == ["mail_suspended"]
    assert auth_world.store.notifications[0].payload == {"reason": "spam"}

    resumed = await auth_world.auth.resume_mail.execute(admin, user.id, CTX)
    assert resumed.mail_suspended_at is None


# - - - Teachers: edit, deactivate - - -


async def test_teacher_names_can_be_edited_but_not_the_email_after_activation(
    auth_world: World,
) -> None:
    """ADM-4: edit a teacher; the login never changes."""
    admin = await admin_of(auth_world)
    teacher = await auth_world.add_user(roles={Role.TEACHER}, login="t.one")

    updated = await auth_world.auth.update_teacher.execute(
        admin,
        teacher.id,
        last_name="Newname",
        first_name=None,
        middle_name="Otchestvo",
        email=None,
        ctx=CTX,
    )
    assert (updated.last_name, updated.middle_name, updated.login) == (
        "Newname",
        "Otchestvo",
        "t.one",
    )
    with pytest.raises(EmailLockedError):
        await auth_world.auth.update_teacher.execute(
            admin,
            teacher.id,
            last_name=None,
            first_name=None,
            middle_name=None,
            email="new@example.org",
            ctx=CTX,
        )


async def test_email_of_a_pending_teacher_can_change_and_resends_the_link(
    auth_world: World,
) -> None:
    """ADM-4: before activation the email is just the link's destination."""
    admin = await admin_of(auth_world)
    created = await auth_world.auth.create_teacher.execute(
        admin.user_id,
        last_name="A",
        first_name="B",
        middle_name=None,
        email="old@example.org",
        ctx=CTX,
    )

    await auth_world.auth.update_teacher.execute(
        admin,
        created.user.id,
        last_name=None,
        first_name=None,
        middle_name=None,
        email="new@example.org",
        ctx=CTX,
    )

    (mail,) = auth_world.email.to("new@example.org", "activation")
    assert mail["link"] != created.activation_url
    token = token_of(mail["link"])
    assert (
        await auth_world.auth.activation_info.execute(token)
    ).login == created.user.login
    with pytest.raises(ActivationLinkInvalidError):
        await auth_world.auth.activation_info.execute(token_of(created.activation_url))


async def test_updating_a_non_teacher_is_not_found(auth_world: World) -> None:
    """The route is for teachers only."""
    admin = await admin_of(auth_world)
    student = await auth_world.add_user()

    with pytest.raises(NotFoundError):
        await auth_world.auth.update_teacher.execute(
            admin,
            student.id,
            last_name="X",
            first_name=None,
            middle_name=None,
            email=None,
            ctx=CTX,
        )


async def test_deactivating_a_teacher_revokes_access_and_kicks_the_academic_task(
    auth_world: World,
) -> None:
    """ADM-4: sessions revoked, future lessons flagged for reassignment."""
    admin = await admin_of(auth_world)
    teacher = await auth_world.add_user(roles={Role.TEACHER}, login="t.one")
    session = auth_world.add_session(teacher)

    result = await auth_world.auth.deactivate_teacher.execute(admin, teacher.id, CTX)

    assert result.status == UserStatus.DEACTIVATED
    assert auth_world.store.sessions[session.id].revoked_at is not None
    assert auth_world.kicker.calls == [
        ("academic.teacher_deactivated", {"teacher_id": str(teacher.id)})
    ]
    assert "user.deactivated" in auth_world.store.audit_types(teacher.id)


# - - - Lists, detail, audit, clients - - -


async def test_user_list_filters_and_paginates(auth_world: World) -> None:
    """UF-ADM-11: search by text, role and status with a cursor."""
    await admin_of(auth_world)
    for index in range(5):
        await auth_world.add_user(
            login=f"stud{index}.x",
            first_name=f"S{index}",
            last_name="Stud",
            recovery_email=f"s{index}@example.org",
        )
    await auth_world.add_user(
        login="teach.er", roles={Role.TEACHER}, recovery_email="te@example.org"
    )

    page = await auth_world.auth.list_users.execute(
        query="stud", role=Role.STUDENT, status=UserStatus.ACTIVE, cursor=None, limit=3
    )
    rest = await auth_world.auth.list_users.execute(
        query="stud",
        role=Role.STUDENT,
        status=UserStatus.ACTIVE,
        cursor=page.next_cursor,
        limit=3,
    )
    teachers = await auth_world.auth.list_teachers.execute(
        query=None, status=None, cursor=None, limit=10
    )

    assert len(page.items) == 3 and page.next_cursor
    assert len(rest.items) == 2 and rest.next_cursor is None
    assert [u.login for u in teachers.items] == ["teach.er"]


async def test_opening_a_student_profile_is_audited(auth_world: World) -> None:
    """GEN-6: views of student profiles are sensitive actions."""
    admin = await admin_of(auth_world)
    student = await auth_world.add_user()
    auth_world.add_session(student)
    auth_world.add_link(student, 555)

    detail = await auth_world.auth.get_user_detail.execute(admin, student.id, CTX)

    assert (len(detail.sessions), len(detail.telegram)) == (1, 1)
    event = next(e for e in auth_world.store.events if e.type == "student.viewed")
    assert (event.user_id, event.actor_id) == (student.id, admin.user_id)


async def test_user_detail_of_an_unknown_user_is_404(auth_world: World) -> None:
    """id/user-not-found."""
    from app.modules.identity.domain.errors import UserNotFoundError
    from app.shared.ids import new_id

    admin = await admin_of(auth_world)

    with pytest.raises(UserNotFoundError):
        await auth_world.auth.get_user_detail.execute(admin, new_id(), CTX)


async def test_audit_log_filters_by_user_type_and_period(auth_world: World) -> None:
    """UF-ADM-13: filter by user, event type and date."""
    admin = await admin_of(auth_world)
    user = await auth_world.add_user()
    await auth_world.auth.block_user.execute(admin, user.id, "x", CTX)
    auth_world.clock.advance(days=2)
    await auth_world.auth.unblock_user.execute(admin, user.id, CTX)

    everything = await auth_world.auth.list_audit.execute(
        user_id=user.id, type=None, since=None, until=None, cursor=None, limit=10
    )
    only_blocks = await auth_world.auth.list_audit.execute(
        user_id=None, type="user.blocked", since=None, until=None, cursor=None, limit=10
    )
    recent = await auth_world.auth.list_audit.execute(
        user_id=user.id,
        type=None,
        since=auth_world.clock.now() - timedelta(days=1),
        until=None,
        cursor=None,
        limit=10,
    )

    assert [e.type for e in everything.items] == ["user.unblocked", "user.blocked"]
    assert [e.type for e in only_blocks.items] == ["user.blocked"]
    assert [e.type for e in recent.items] == ["user.unblocked"]
    assert everything.actors[admin.user_id].login == "root.admin"


async def test_oauth_clients_list_hides_our_own_and_can_be_verified(
    auth_world: World,
) -> None:
    """MCP-3: Administration verifies dynamically registered clients."""
    from tests.fakes.identity.hydra import client

    admin = await admin_of(auth_world)
    auth_world.hydra.clients["claude"] = client("claude")
    auth_world.hydra.clients["miniapp"] = client("miniapp")
    user = await auth_world.add_user()
    auth_world.add_connector(
        user, hydra_client_id="claude", last_used_at=auth_world.clock.now()
    )

    listed = await auth_world.auth.list_oauth_clients.execute()
    assert [(c.client_id, c.verified, c.dynamic) for c in listed] == [
        ("claude", False, True)
    ]
    assert listed[0].last_used_at == auth_world.clock.now()

    view = await auth_world.auth.verify_oauth_client.execute(
        admin, "claude", verified=True, ctx=CTX
    )
    assert view.verified is True
    assert auth_world.hydra.last("set_client_metadata")["metadata"]["verified"] is True
    assert "oauth_client.verified" in auth_world.store.audit_types()
    with pytest.raises(NotFoundError):
        await auth_world.auth.verify_oauth_client.execute(
            admin, "missing", verified=True, ctx=CTX
        )
