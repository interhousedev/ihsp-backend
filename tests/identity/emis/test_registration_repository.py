"""Integration: the EMIS use cases and RegistrationRepository on a real PostgreSQL."""

from datetime import UTC, datetime
from uuid import UUID

from app.modules.identity.application.register_errors import EmisAlreadyLinkedError
from app.modules.identity.application.register_models import NewStudentAccount
from app.modules.identity.infrastructure.emis.uow import EmisSqlUnitOfWork
from app.modules.identity.infrastructure.orm.user import User
from app.shared.actor import Actor, Role
from app.shared.base_error import ConflictError
from app.shared.contracts.identity import UserStatus
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.identity.emis.world import NEW_PASSWORD, World, build_world

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def make_uow(sessionmaker: async_sessionmaker[AsyncSession]) -> EmisSqlUnitOfWork:
    return EmisSqlUnitOfWork(sessionmaker, noop_outbox_writer, noop_audit_writer)


def new_student(
    *,
    user_id: UUID | None = None,
    login: str = "brastilov.aleksey",
    email: str = "aleksey@example.com",
    emis_student_id: int = 78218,
    activates_import: bool = False,
) -> NewStudentAccount:
    return NewStudentAccount(
        user_id=user_id or new_id(),
        activates_import=activates_import,
        login=login,
        password_hash="$argon2id$fake",
        first_name="Aleksey",
        last_name="Brastilov",
        middle_name="Mixaylovich",
        recovery_email=email,
        verified_at=NOW,
        emis_student_id=emis_student_id,
        emis_vault_ref=new_id(),
        locale="uz",
    )


async def add_user(
    db_session: AsyncSession,
    *,
    login: str | None,
    status: UserStatus = UserStatus.ACTIVE,
    email: str | None = None,
    emis_student_id: int | None = None,
) -> UUID:
    user = User(
        id=new_id(),
        login=login,
        first_name="Petr",
        last_name="Petrov",
        roles=["student"],
        recovery_email=email,
        status=status.value,
        emis_student_id=emis_student_id,
        preferences={},
    )
    db_session.add(user)
    await db_session.flush()
    return user.id


async def test_save_student_inserts_an_active_student_linked_to_emis(
    db_session: AsyncSession, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """ID-1, ID-4, ID-6: the row has the login, email, EMIS link and locale."""
    account = new_student()

    async with make_uow(sessionmaker_in_tx) as uow:
        await uow.accounts.save_student(account)
        await uow.commit()
    row = (
        await db_session.execute(select(User).where(User.id == account.user_id))
    ).scalar_one()

    assert (row.login, row.status, row.roles) == (
        "brastilov.aleksey",
        "active",
        ["student"],
    )
    assert row.recovery_email == "aleksey@example.com"
    assert row.recovery_email_verified_at == NOW
    assert (row.emis_student_id, row.emis_status) == (78218, "active")
    assert row.emis_vault_ref == account.emis_vault_ref
    assert row.preferences == {"locale": "uz"}
    assert row.password_hash == "$argon2id$fake"


async def test_save_student_activates_an_imported_account(
    db_session: AsyncSession, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """ACA-18: the import's row becomes the active account."""
    imported = await add_user(db_session, login=None, status=UserStatus.UNREGISTERED)

    async with make_uow(sessionmaker_in_tx) as uow:
        await uow.accounts.save_student(
            new_student(user_id=imported, activates_import=True)
        )
        await uow.commit()
        snapshot = await uow.accounts.get(imported)

    assert snapshot is not None
    assert snapshot.status is UserStatus.ACTIVE
    assert (snapshot.login, snapshot.first_name) == ("brastilov.aleksey", "Aleksey")
    assert snapshot.locale == "uz"


async def test_an_import_that_is_no_longer_unregistered_is_a_conflict(
    db_session: AsyncSession, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """ID-3: two registrations cannot both claim one import."""
    taken = await add_user(db_session, login="someone.else", emis_student_id=5)

    with pytest.raises(ConflictError):
        async with make_uow(sessionmaker_in_tx) as uow:
            await uow.accounts.save_student(
                new_student(user_id=taken, activates_import=True)
            )


async def test_lookup_by_id_and_by_emis_profile(
    db_session: AsyncSession, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """ID-3: one EMIS profile, one account."""
    user_id = await add_user(db_session, login="a.b", emis_student_id=777)

    async with make_uow(sessionmaker_in_tx) as uow:
        by_emis = await uow.accounts.get_by_emis_student_id(777)
        missing = await uow.accounts.get_by_emis_student_id(778)
        by_id = await uow.accounts.get(user_id)

    assert by_emis is not None and by_id is not None
    assert by_emis.id == by_id.id == user_id
    assert missing is None
    assert by_id.locale == "ru"  # the default when preferences are empty


async def test_taken_logins_match_the_prefix_and_ignore_wildcards(
    db_session: AsyncSession, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """ID-5: brastilov.aleksey, brastilov.aleksey2 are taken; nothing else."""
    await add_user(db_session, login="Brastilov.Aleksey")
    await add_user(db_session, login="brastilov.aleksey2")
    await add_user(db_session, login="brastilov.alex")
    await add_user(db_session, login=None, status=UserStatus.UNREGISTERED)

    async with make_uow(sessionmaker_in_tx) as uow:
        taken = await uow.accounts.taken_logins("brastilov.aleksey")
        wildcard = await uow.accounts.taken_logins("%")

    assert taken == {"brastilov.aleksey", "brastilov.aleksey2"}
    assert wildcard == set()


async def test_email_in_use_is_case_insensitive_and_can_exclude_a_user(
    db_session: AsyncSession, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """ID-4: the unique index is on lower(recovery_email)."""
    owner = await add_user(db_session, login="o.w", email="Owner@Example.com")

    async with make_uow(sessionmaker_in_tx) as uow:
        assert await uow.accounts.email_in_use("owner@example.COM", except_user_id=None)
        assert not await uow.accounts.email_in_use(
            "owner@example.com", except_user_id=owner
        )
        assert not await uow.accounts.email_in_use("x@example.com", except_user_id=None)


async def test_a_deleted_account_gives_its_emis_profile_back(
    db_session: AsyncSession, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """ID-29: only deleted accounts are detached."""
    deleted = await add_user(
        db_session, login="d.d", status=UserStatus.DELETED, emis_student_id=10
    )
    live = await add_user(db_session, login="l.l", emis_student_id=11)

    async with make_uow(sessionmaker_in_tx) as uow:
        await uow.accounts.release_deleted_emis_link(10)
        await uow.accounts.release_deleted_emis_link(11)
        first = await uow.accounts.get(deleted)
        second = await uow.accounts.get(live)

    assert first is not None and second is not None
    assert (first.emis_student_id, second.emis_student_id) == (None, 11)


async def test_credentials_status_deletion_and_secret_updates(
    db_session: AsyncSession, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """ID-8, ID-28, ID-29: the small writes of reclaim, update and deletion."""
    user_id = await add_user(db_session, login="a.b", email="old@example.com")

    async with make_uow(sessionmaker_in_tx) as uow:
        await uow.accounts.lock_logins()
        await uow.accounts.set_credentials(
            user_id, password_hash="h2", recovery_email="new@example.com", now=NOW
        )
        await uow.accounts.set_emis_status(user_id, "needs_reauth")
        await uow.accounts.mark_deleted(user_id, NOW)
        await uow.accounts.clear_emis_secret(user_id)
        snapshot = await uow.accounts.get(user_id)
        await uow.commit()

    row = (
        await db_session.execute(
            select(User)
            .where(User.id == user_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert snapshot is not None
    assert snapshot.status is UserStatus.DELETED
    assert (snapshot.password_hash, snapshot.recovery_email) == (
        "h2",
        "new@example.com",
    )
    assert (snapshot.emis_vault_ref, snapshot.emis_status) == (None, None)
    assert row.recovery_email_verified_at == NOW
    assert row.deleted_at == NOW


async def test_registration_and_deletion_through_the_sql_unit_of_work(
    db_session: AsyncSession,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
) -> None:
    """UF-ID-01, UF-ID-16: the use cases on the real tables."""
    world: World = build_world(
        redis, clock, kicker, uow_factory=lambda: make_uow(sessionmaker_in_tx)
    )

    _, registered = await world.register()

    row = (
        await db_session.execute(select(User).where(User.id == registered.user_id))
    ).scalar_one()
    assert (row.login, row.status) == ("abdullayev.alisher", "active")
    assert row.recovery_email == "aleksey@example.com"
    assert (row.emis_student_id, row.emis_status) == (78201, "active")
    assert row.preferences == {"locale": "en"}
    assert row.emis_vault_ref in world.store.secrets
    with pytest.raises(EmisAlreadyLinkedError):
        await world.register_start.execute(
            emis_login="student01", emis_password="password", ip="10.0.0.2", locale="ru"
        )

    closes_on = await world.delete_account.execute(
        Actor(user_id=registered.user_id, roles=frozenset({Role.STUDENT})),
        password=NEW_PASSWORD,
        otp_code=None,
        ip=None,
        user_agent=None,
    )
    await db_session.refresh(row)

    assert row.status == "pending_deletion"
    assert row.deletion_requested_at == clock.now()
    assert closes_on.isoformat() == "2026-11-05"
