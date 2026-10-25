"""MAIL-1, MAIL-9: only mailboxes of active students are accepted."""

from app.shared.actor import Role
from app.shared.contracts.identity import UserRef, UserStatus
from tests.mail.world import MailWorld

import pytest


async def test_the_address_of_an_active_student_resolves_to_the_user(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-1: {login}@mail.ihsu.uz is the student's mailbox."""
    assert await world.resolve_mailbox.execute("aleksey.brastilov@mail.ihsu.uz") == (
        student.id
    )


async def test_the_address_is_case_insensitive_and_may_have_angle_brackets(
    world: MailWorld, student: UserRef
) -> None:
    """MAIL-9: SMTP clients send any case."""
    assert await world.resolve_mailbox.execute("<Aleksey.Brastilov@MAIL.ihsu.uz>") == (
        student.id
    )


@pytest.mark.parametrize(
    "address",
    [
        "nobody@mail.ihsu.uz",
        "aleksey.brastilov@ihsu.uz",
        "aleksey.brastilov@gmail.com",
        "aleksey.brastilov",
        "@mail.ihsu.uz",
        "",
    ],
)
async def test_other_addresses_are_refused(
    world: MailWorld, student: UserRef, address: str
) -> None:
    """MAIL-9: unknown logins and foreign domains."""
    assert await world.resolve_mailbox.execute(address) is None


async def test_inactive_users_have_no_mailbox(world: MailWorld) -> None:
    """MAIL-9: blocked, deactivated and unregistered accounts."""
    for status in (UserStatus.BLOCKED, UserStatus.DEACTIVATED, UserStatus.DELETED):
        world.student(f"user.{status.value}", status=status)

    for status in (UserStatus.BLOCKED, UserStatus.DEACTIVATED, UserStatus.DELETED):
        assert (
            await world.resolve_mailbox.execute(f"user.{status.value}@mail.ihsu.uz")
            is None
        )


async def test_staff_have_no_mailbox(world: MailWorld) -> None:
    """MAIL-1: mailboxes belong to students."""
    world.student("teacher.one", roles=frozenset({Role.TEACHER}))

    assert await world.resolve_mailbox.execute("teacher.one@mail.ihsu.uz") is None


def test_address_domain_helpers() -> None:
    """MAIL-9: domain and login extraction."""
    from app.modules.mail.domain.addresses import address_domain, login_from_address

    assert address_domain("Anna <Anna@Example.COM.>") == "example.com"
    assert address_domain("no-at-sign") is None
    assert address_domain("trailing@") is None
    assert login_from_address("a.b@MAIL.ihsu.uz", "mail.ihsu.uz") == "a.b"
