"""Repositories of the identity module against PostgreSQL (migrations' ORM models)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.domain.session import LoginSession
from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.domain.user import ActivationPurpose, User
from app.modules.identity.infrastructure.uow import IdentityUnitOfWork
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft
from tests.fakes.outbox import InMemoryOutbox
from tests.identity.support import make_user

import pytest
from sqlalchemy.exc import IntegrityError

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
UowMaker = Callable[[], IdentityUnitOfWork]


def user_row(**fields: Any) -> User:
    """A user with a unique login and email."""
    suffix = new_id().hex[-10:]
    defaults = {
        "login": f"user.{suffix}",
        "recovery_email": f"{suffix}@example.org",
        "recovery_email_verified_at": NOW,
    }
    return make_user(**{**defaults, **fields})


# - - - Users - - -


async def test_user_round_trips_every_field(make_uow: UowMaker) -> None:
    """The ORM mapping keeps roles, enums, preferences and the activation data."""
    user = user_row(
        middle_name="Otchestvo",
        password_hash="$argon2id$x",
        roles={Role.STUDENT, Role.ADMIN},
        otp_enabled=True,
        otp_via_email=True,
        auth_epoch=4,
        activation_token_hash="a" * 64,
        activation_expires_at=NOW + timedelta(hours=72),
        activation_purpose=ActivationPurpose.RESET_PASSWORD,
        emis_student_id=78218,
        emis_vault_ref=new_id(),
        emis_status="needs_reauth",
        mail_suspended_at=NOW,
        preferences={"locale": "uz", "marks_values": [4, 5]},
        last_login_at=NOW,
        otp_reset_effective_at=NOW,
        otp_reset_request_id=new_id(),
    )
    async with make_uow() as uow:
        await uow.users.add(user)
        await uow.commit()

    async with make_uow() as uow:
        loaded = await uow.users.get(user.id)

    assert loaded is not None
    loaded.created_at = None
    expected = user
    expected.created_at = None
    assert loaded == expected
    assert loaded.status == UserStatus.ACTIVE and loaded.roles == {
        Role.STUDENT,
        Role.ADMIN,
    }


async def test_user_lookups_are_case_insensitive(make_uow: UowMaker) -> None:
    """ID-12: login and recovery email match without regard to case."""
    user = user_row(login="Brastilov.Aleksey", recovery_email="Ali@Example.ORG")
    async with make_uow() as uow:
        await uow.users.add(user)
        assert (await uow.users.get_by_login("brastilov.ALEKSEY")).id == user.id
        assert (await uow.users.get_by_recovery_email("ali@example.org")).id == user.id
        assert await uow.users.get_by_login("nobody") is None
        assert await uow.users.email_taken("ALI@example.org") is True
        assert (
            await uow.users.email_taken("ali@example.org", except_user_id=user.id)
            is False
        )


async def test_recovery_email_is_unique_ignoring_case(make_uow: UowMaker) -> None:
    """Models: unique index on lower(recovery_email)."""
    async with make_uow() as uow:
        await uow.users.add(user_row(recovery_email="same@example.org"))
        with pytest.raises(IntegrityError):
            await uow.users.add(user_row(recovery_email="SAME@example.org"))


async def test_save_updates_and_lookups_by_token_and_request(
    make_uow: UowMaker,
) -> None:
    """Activation hash and OTP reset request lookups."""
    user = user_row()
    request_id = new_id()
    async with make_uow() as uow:
        await uow.users.add(user)
        user.activation_token_hash = "b" * 64
        user.otp_reset_request_id = request_id
        user.status = UserStatus.BLOCKED
        await uow.users.save(user)
        assert (
            await uow.users.get_by_activation_hash("b" * 64)
        ).status == UserStatus.BLOCKED
        assert (await uow.users.get_by_otp_reset_request(request_id)).id == user.id
        assert await uow.users.get_epoch(user.id) == 0
        assert await uow.users.get_epoch(new_id()) is None


async def test_logins_with_prefix_are_lowercase_and_escape_wildcards(
    make_uow: UowMaker,
) -> None:
    """ID-5: collision detection for kalandarova.gavxar, gavxar2, ..."""
    async with make_uow() as uow:
        await uow.users.add(user_row(login="Kalandarova.Gavxar"))
        await uow.users.add(user_row(login="kalandarova.gavxar2"))
        await uow.users.add(user_row(login="kalandarova_gavxar"))

        found = await uow.users.logins_with_prefix("kalandarova.gavxar")

    assert found == {"kalandarova.gavxar", "kalandarova.gavxar2"}


async def test_search_filters_and_paginates_newest_first(make_uow: UowMaker) -> None:
    """UF-ADM-11: text, role and status filters with a cursor."""
    marker = new_id().hex[-8:]
    created = []
    async with make_uow() as uow:
        for index in range(5):
            user = user_row(first_name=f"Zed{marker}{index}")
            created.append(user)
            await uow.users.add(user)
        await uow.users.add(
            user_row(
                first_name=f"Zed{marker}x",
                roles={Role.TEACHER},
                status=UserStatus.BLOCKED,
            )
        )

        first = await uow.users.search(
            query=f"zed{marker}",
            roles=[Role.STUDENT],
            status=UserStatus.ACTIVE,
            cursor=None,
            limit=3,
        )
        second = await uow.users.search(
            query=f"zed{marker}",
            roles=[Role.STUDENT],
            status=UserStatus.ACTIVE,
            cursor=first.next_cursor,
            limit=3,
        )

    ids = [u.id for u in first.items] + [u.id for u in second.items]
    assert ids == [u.id for u in sorted(created, key=lambda u: u.id, reverse=True)]
    assert first.next_cursor and second.next_cursor is None


async def test_search_treats_percent_and_underscore_literally(
    make_uow: UowMaker,
) -> None:
    """A search for % must not match everything."""
    async with make_uow() as uow:
        await uow.users.add(user_row())
        page = await uow.users.search(
            query="%", roles=[], status=None, cursor=None, limit=10
        )

    assert page.items == []


async def test_directory_search_and_roles_only_see_active_users(
    make_uow: UowMaker,
) -> None:
    """Contract: search_users and user_ids_with_roles."""
    marker = new_id().hex[-8:]
    async with make_uow() as uow:
        teacher = user_row(first_name=f"Gav{marker}", roles={Role.TEACHER})
        await uow.users.add(teacher)
        await uow.users.add(
            user_row(
                first_name=f"Gav{marker}",
                roles={Role.TEACHER},
                status=UserStatus.DEACTIVATED,
            )
        )

        found = await uow.users.search_active(
            f"gav{marker}", roles=[Role.TEACHER], limit=10
        )
        ids = await uow.users.ids_with_roles([Role.TEACHER])

    assert [u.id for u in found] == [teacher.id]
    assert teacher.id in ids and len(found) == 1


async def test_merge_preferences_is_one_atomic_statement(make_uow: UowMaker) -> None:
    """Models: arrays and jsonb change atomically."""
    user = user_row(preferences={"locale": "uz", "theme": "light"})
    async with make_uow() as uow:
        await uow.users.add(user)
        merged = await uow.users.merge_preferences(
            user.id, {"theme": "dark", "alerts_drops": False}
        )
        again = await uow.users.get(user.id)

    assert merged == {"locale": "uz", "theme": "dark", "alerts_drops": False}
    assert again.preferences == merged


async def test_due_otp_resets_and_purgeable_queries(make_uow: UowMaker) -> None:
    """Jobs: identity.apply_otp_resets and identity.purge_deleted_users."""
    due = user_row(otp_reset_effective_at=NOW - timedelta(minutes=1))
    later = user_row(otp_reset_effective_at=NOW + timedelta(hours=1))
    old_deleted = user_row(
        status=UserStatus.DELETED, deleted_at=NOW - timedelta(days=31)
    )
    fresh_deleted = user_row(
        status=UserStatus.DELETED, deleted_at=NOW - timedelta(days=2)
    )
    purged = user_row(
        status=UserStatus.DELETED,
        deleted_at=NOW - timedelta(days=40),
        first_name="Deleted",
    )
    async with make_uow() as uow:
        for user in (due, later, old_deleted, fresh_deleted, purged):
            await uow.users.add(user)

        resets = {u.id for u in await uow.users.due_otp_resets(NOW)}
        purgeable = {
            u.id for u in await uow.users.purgeable(NOW - timedelta(days=30), 100)
        }

    assert due.id in resets and later.id not in resets
    assert purgeable >= {old_deleted.id} and not purgeable & {
        fresh_deleted.id,
        purged.id,
    }


# - - - Sessions - - -


def make_session(user: User, **fields: Any) -> LoginSession:
    """A session of the user."""
    defaults = {
        "id": new_id(),
        "ip": "203.0.113.5",
        "user_agent": "pytest",
        "expires_at": NOW + timedelta(days=30),
        "last_seen_at": NOW,
        "amr": ["pwd"],
    }
    return LoginSession(user_id=user.id, **{**defaults, **fields})


async def test_session_round_trip_with_inet_and_hydra_sid(make_uow: UowMaker) -> None:
    """Models: ip is inet, hydra_sid unique."""
    user = user_row()
    session = make_session(
        user, hydra_sid="sid-1", mfa_at=NOW, amr=["pwd", "otp"], ip="2001:db8::1"
    )
    async with make_uow() as uow:
        await uow.users.add(user)
        await uow.sessions.add(session)
        loaded = await uow.sessions.get(session.id)
        by_sid = await uow.sessions.get_by_hydra_sid("sid-1")

    assert loaded is not None and by_sid is not None
    assert (loaded.ip, loaded.amr, loaded.mfa_at, loaded.hydra_sid) == (
        "2001:db8::1",
        ["pwd", "otp"],
        NOW,
        "sid-1",
    )
    assert by_sid.id == session.id


async def test_active_sessions_exclude_revoked_and_expired(make_uow: UowMaker) -> None:
    """ID-17: the sessions list shows live sessions only."""
    user = user_row()
    live = make_session(user, last_seen_at=NOW)
    older = make_session(user, last_seen_at=NOW - timedelta(hours=1))
    revoked = make_session(user, revoked_at=NOW)
    expired = make_session(user, expires_at=NOW - timedelta(seconds=1))
    async with make_uow() as uow:
        await uow.users.add(user)
        for session in (older, live, revoked, expired):
            await uow.sessions.add(session)

        listed = await uow.sessions.list_active(user.id, NOW)
        latest = await uow.sessions.latest_active(user.id, NOW)

    assert [s.id for s in listed] == [live.id, older.id]
    assert latest is not None and latest.id in {live.id, older.id}


async def test_revoke_and_revoke_all(make_uow: UowMaker) -> None:
    """GEN-5: revoke returns the session only when it was active."""
    user = user_row()
    sessions = [make_session(user) for _ in range(3)]
    async with make_uow() as uow:
        await uow.users.add(user)
        for session in sessions:
            await uow.sessions.add(session)

        first = await uow.sessions.revoke(sessions[0].id, NOW)
        again = await uow.sessions.revoke(sessions[0].id, NOW)
        rest = await uow.sessions.revoke_all(user.id, NOW, except_id=sessions[1].id)

    assert first is not None and first.revoked_at == NOW
    assert again is None
    assert [s.id for s in rest] == [sessions[2].id]


async def test_touch_updates_last_seen_at_at_most_once_a_minute(
    make_uow: UowMaker,
) -> None:
    """Models: last_seen_at is updated at most once a minute."""
    user = user_row()
    session = make_session(user, last_seen_at=NOW)
    async with make_uow() as uow:
        await uow.users.add(user)
        await uow.sessions.add(session)

        await uow.sessions.touch(
            session.id, NOW + timedelta(seconds=30), min_interval=timedelta(minutes=1)
        )
        early = (await uow.sessions.get(session.id)).last_seen_at
        await uow.sessions.touch(
            session.id, NOW + timedelta(seconds=90), min_interval=timedelta(minutes=1)
        )
        late = (await uow.sessions.get(session.id)).last_seen_at

    assert early == NOW and late == NOW + timedelta(seconds=90)


async def test_save_session_rewrites_the_mutable_fields(make_uow: UowMaker) -> None:
    """The same browser logging in again reuses its row."""
    user = user_row()
    session = make_session(user, hydra_sid="sid-9")
    async with make_uow() as uow:
        await uow.users.add(user)
        await uow.sessions.add(session)
        session.mfa_at = NOW
        session.amr = ["pwd", "otp"]
        session.revoked_at = None
        await uow.sessions.save(session)
        loaded = await uow.sessions.get(session.id)

    assert (loaded.mfa_at, loaded.amr) == (NOW, ["pwd", "otp"])


# - - - Telegram links - - -


async def test_telegram_links_are_unique_per_telegram_account(
    make_uow: UowMaker,
) -> None:
    """ID-18: one Telegram account, one user."""
    one, two = user_row(), user_row()
    tg_id = 9_000_000_000 + new_id().int % 1_000_000
    async with make_uow() as uow:
        await uow.users.add(one)
        await uow.users.add(two)
        await uow.telegram_links.add(
            TelegramLink(
                tg_id, one.id, "Ali", username="ali", linked_at=NOW, last_seen_at=NOW
            )
        )
        with pytest.raises(IntegrityError):
            await uow.telegram_links.add(TelegramLink(tg_id, two.id, "Bob"))


async def test_telegram_link_crud(make_uow: UowMaker) -> None:
    """bigint ids, save, list and delete_all."""
    user = user_row()
    ids = [
        9_100_000_000_000 + new_id().int % 1_000_000,
        9_200_000_000_000 + new_id().int % 1_000_000,
    ]
    async with make_uow() as uow:
        await uow.users.add(user)
        for tg_id in ids:
            await uow.telegram_links.add(
                TelegramLink(tg_id, user.id, "Ali", linked_at=NOW, last_seen_at=NOW)
            )
        link = await uow.telegram_links.get(ids[0])
        link.otp_delivery = False
        link.blocked_at = NOW
        await uow.telegram_links.save(link)
        reloaded = await uow.telegram_links.get(ids[0])
        listed = await uow.telegram_links.list_for_user(user.id)
        grouped = await uow.telegram_links.list_for_users([user.id, new_id()])
        removed = await uow.telegram_links.delete_all_for_user(user.id)
        gone = await uow.telegram_links.delete(ids[0])

    assert (reloaded.otp_delivery, reloaded.blocked_at) == (False, NOW)
    assert [link.telegram_user_id for link in listed] == ids
    assert len(grouped[user.id]) == 2
    assert {link.telegram_user_id for link in removed} == set(ids) and gone is False


# - - - Connectors - - -


def make_connector(user: User, **fields: Any) -> McpConnector:
    """A student connector."""
    defaults = {
        "id": new_id(),
        "name": "Claude",
        "server": "student",
        "scopes": ["schedule:read", "marks:read"],
        "expires_at": NOW + timedelta(days=30),
    }
    return McpConnector(user_id=user.id, **{**defaults, **fields})


async def test_connector_round_trip_and_token_lookup(make_uow: UowMaker) -> None:
    """MCP-2: the hash is the lookup key; course_ids is an array."""
    user = user_row()
    courses = [new_id(), new_id()]
    token_hash = new_id().hex + new_id().hex
    connector = make_connector(
        user,
        server="lms",
        course_ids=courses,
        token_hash=token_hash,
        token_prefix="abcd1234",
    )
    async with make_uow() as uow:
        await uow.users.add(user)
        await uow.connectors.add(connector)
        loaded = await uow.connectors.get_by_token_hash(token_hash)

    assert loaded is not None
    assert (loaded.course_ids, loaded.scopes, loaded.kind) == (
        courses,
        connector.scopes,
        "token",
    )


async def test_oauth_connector_has_no_hash(make_uow: UowMaker) -> None:
    """Models: OAuth connectors live in Hydra and store the client id."""
    user = user_row()
    connector = make_connector(user, hydra_client_id="claude")
    async with make_uow() as uow:
        await uow.users.add(user)
        await uow.connectors.add(connector)
        loaded = await uow.connectors.get(connector.id)

    assert loaded.kind == "oauth" and loaded.hydra_client_id == "claude"


async def test_revoke_all_touch_and_last_use_per_client(make_uow: UowMaker) -> None:
    """MCP-4, GEN-5."""
    user = user_row()
    one = make_connector(user, hydra_client_id="claude")
    two = make_connector(user, hydra_client_id="claude")
    other = make_connector(user, hydra_client_id="gpt")
    async with make_uow() as uow:
        await uow.users.add(user)
        for connector in (one, two, other):
            await uow.connectors.add(connector)
        await uow.connectors.touch_last_used(
            one.id, NOW, min_interval=timedelta(minutes=1)
        )
        await uow.connectors.touch_last_used(
            one.id, NOW + timedelta(seconds=10), min_interval=timedelta(minutes=1)
        )
        await uow.connectors.touch_last_used(
            two.id, NOW + timedelta(hours=1), min_interval=timedelta(minutes=1)
        )
        used = await uow.connectors.last_used_by_client(["claude", "gpt", "none"])
        listed = await uow.connectors.list_for_user(user.id)
        revoked = await uow.connectors.revoke_all_for_user(user.id, NOW)
        again = await uow.connectors.revoke_all_for_user(user.id, NOW)

    assert used == {"claude": NOW + timedelta(hours=1), "gpt": None, "none": None}
    assert [c.id for c in listed] == sorted([one.id, two.id, other.id], reverse=True)
    assert len(revoked) == 3 and again == []


# - - - Audit events - - -


async def test_audit_events_are_written_and_read_newest_first_with_a_cursor(
    make_uow: UowMaker, outbox: InMemoryOutbox
) -> None:
    """GEN-6: drafts become rows at commit; invalid IPs never fail the commit."""
    user = user_row()
    other = user_row()
    async with make_uow() as uow:
        await uow.users.add(user)
        await uow.users.add(other)
        for index in range(4):
            uow.audit(
                AuditDraft(
                    type=f"test.event{index}",
                    user_id=user.id,
                    actor_id=other.id,
                    ip="203.0.113.5" if index else "not-an-ip",
                    user_agent="pytest",
                    metadata={"n": index},
                )
            )
        uow.audit(AuditDraft(type="test.other", user_id=other.id))
        await uow.commit()

    async with make_uow() as uow:
        first = await uow.audit_events.search(
            user_id=user.id, type=None, since=None, until=None, cursor=None, limit=3
        )
        second = await uow.audit_events.search(
            user_id=user.id,
            type=None,
            since=None,
            until=None,
            cursor=first.next_cursor,
            limit=3,
        )
        typed = await uow.audit_events.search(
            user_id=None,
            type="test.other",
            since=None,
            until=None,
            cursor=None,
            limit=3,
        )
        recent = await uow.audit_events.recent_for_user(user.id, 2)

    assert len(first.items) == 3 and first.next_cursor
    assert len(second.items) == 1 and second.next_cursor is None
    events = {e.type: e for e in first.items + second.items}
    assert set(events) == {f"test.event{i}" for i in range(4)}
    assert events["test.event0"].ip is None  # "not-an-ip" was dropped
    assert events["test.event1"].ip == "203.0.113.5"
    assert (events["test.event2"].actor_id, events["test.event2"].metadata) == (
        other.id,
        {"n": 2},
    )
    assert [e.type for e in typed.items] == ["test.other"]
    assert len(recent) == 2
