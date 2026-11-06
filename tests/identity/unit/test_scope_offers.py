"""A7: offers of new MCP scopes, their decisions and the call log retention."""

from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.domain.scope_offer import DecideResult, hash_offer_token
from app.modules.identity.domain.user import User
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.contracts.mcp_calls import McpCallRecord
from app.shared.ids import new_id
from app.shared.mcp_scopes import RELEASE_2026_11, RELEASES, ScopeRelease
from app.shared.notifications import NotificationType
from tests.identity.support import World

ALREADY = {"schedule:read", "marks:read"}


def _connector(user: User, *, server: str = "student", **fields: Any) -> McpConnector:
    connector = McpConnector(
        id=new_id(),
        user_id=user.id,
        name=fields.pop("name", "Claude"),
        server=server,
        scopes=fields.pop("scopes", sorted(ALREADY)),
        token_hash=fields.pop("token_hash", f"hash-{new_id()}"),
        **fields,
    )
    return connector


async def _student(world: World, *connectors: dict[str, Any]) -> User:
    user = await world.add_user(roles={Role.STUDENT}, login=f"s{new_id().hex[:8]}")
    for fields in connectors:
        made = _connector(user, **fields)
        world.store.connectors[made.id] = made
    return user


def _token(world: World) -> str:
    return str(world.store.notifications[-1].payload["token"])


async def test_an_offer_lists_read_and_write_scopes_and_the_keys(
    auth_world: World,
) -> None:
    """A7: the notification names write scopes apart, and every affected key."""
    user = await _student(auth_world, {"name": "Claude"}, {"name": "Cursor"})

    assert await auth_world.auth.offer_mcp_scopes.execute() == 1

    [draft] = auth_world.store.notifications
    assert draft.user_id == user.id
    assert draft.type == NotificationType.MCP_SCOPE_OFFER
    assert draft.dedupe_key == f"mcp-scopes:{RELEASE_2026_11}:{user.id}"
    assert draft.payload["write_scopes"] == [
        "sync:run",
        "flashcards:delete",
        "tests:write",
        "notebooks:write",
    ]
    assert "teachers:read" in draft.payload["read_scopes"]
    assert "sync:run" not in draft.payload["read_scopes"]
    assert sorted(draft.payload["connector_names"]) == ["Claude", "Cursor"]
    assert draft.payload["summary_key"] == "mcp-release-2026-11-mcp-1"


async def test_the_token_is_only_stored_hashed_and_has_128_bits(
    auth_world: World,
) -> None:
    """A7: the offer row keeps a hash; the token fits the callback."""
    await _student(auth_world, {})

    await auth_world.auth.offer_mcp_scopes.execute()

    token = _token(auth_world)
    [offer] = auth_world.store.scope_offers.values()
    assert len(token) == 22
    assert offer.token_hash == hash_offer_token(token)
    assert offer.token_hash != token


async def test_running_the_job_again_sends_nothing(auth_world: World) -> None:
    """A7: idempotent per release: a re-run, a crash or two schedulers send once."""
    await _student(auth_world, {})

    assert await auth_world.auth.offer_mcp_scopes.execute() == 1
    assert await auth_world.auth.offer_mcp_scopes.execute() == 0

    assert len(auth_world.store.notifications) == 1
    assert len(auth_world.store.scope_offers) == 1


async def test_the_admin_server_is_never_offered(auth_world: World) -> None:
    """D7: an administrator's connector gets no offer: a button would skip the OTP."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, login="root.adm")
    made = _connector(admin, server="admin", scopes=["people:read"])
    auth_world.store.connectors[made.id] = made

    assert await auth_world.auth.offer_mcp_scopes.execute() == 0

    assert auth_world.store.notifications == []


async def test_an_admin_release_in_the_registry_is_refused(
    auth_world: World, monkeypatch: Any
) -> None:
    """D7: even a release naming the admin server sends and grants nothing."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, login="root.adm")
    made = _connector(admin, server="admin", scopes=["people:read"])
    auth_world.store.connectors[made.id] = made
    release = ScopeRelease("x", "admin", ("audit:read",), "mcp-release-2026-11-mcp-1")
    monkeypatch.setattr(
        "app.modules.identity.application.offer_mcp_scopes.RELEASES", (release,)
    )

    assert await auth_world.auth.offer_mcp_scopes.execute() == 0


async def test_who_gets_no_offer(auth_world: World) -> None:
    """A7: revoked, expired, complete keys and deactivated users are skipped."""
    now = auth_world.clock.now()
    await _student(auth_world, {"revoked_at": now})
    await _student(auth_world, {"expires_at": now - timedelta(days=1)})
    await _student(auth_world, {"scopes": list(RELEASES[0].scopes)})
    blocked = await _student(auth_world, {})
    auth_world.store.users[blocked.id].status = UserStatus.BLOCKED
    teacher = await auth_world.add_user(roles={Role.TEACHER}, login="t.one")
    made = _connector(teacher)  # the role lost the student server
    auth_world.store.connectors[made.id] = made

    assert await auth_world.auth.offer_mcp_scopes.execute() == 0


async def test_only_missing_scopes_are_offered(auth_world: World) -> None:
    """A7: a scope every key holds already is not offered again."""
    await _student(auth_world, {"extra_scopes": ["sync:run"]})

    await auth_world.auth.offer_mcp_scopes.execute()

    [offer] = auth_world.store.scope_offers.values()
    assert "sync:run" not in offer.scopes
    assert "teachers:read" in offer.scopes


async def test_grant_widens_tokens_directly_and_oauth_through_the_overlay(
    auth_world: World,
) -> None:
    """A7: a JWT keeps its `scp`, so OAuth connectors take `extra_scopes`."""
    user = await _student(
        auth_world,
        {"name": "Token"},
        {"name": "OAuth", "token_hash": None, "hydra_client_id": "c1"},
    )
    await auth_world.auth.offer_mcp_scopes.execute()

    outcome = await auth_world.auth.decide_scope_offer.execute(
        _token(auth_world), user.id, grant=True
    )

    assert outcome.result == DecideResult.GRANTED
    by_name = {c.name: c for c in auth_world.store.connectors.values()}
    assert set(RELEASES[0].scopes) <= set(by_name["Token"].scopes)
    assert by_name["Token"].extra_scopes == []
    assert by_name["OAuth"].scopes == sorted(ALREADY)
    assert set(RELEASES[0].scopes) == set(by_name["OAuth"].extra_scopes)
    events = [
        e for e in auth_world.store.audits if e.type == "connector.scopes_extended"
    ]
    assert len(events) == 2
    assert all(
        e.metadata
        and e.metadata["via"] == "telegram"
        and e.metadata["release_id"] == RELEASE_2026_11
        for e in events
    )


async def test_replay_after_a_grant_changes_nothing(auth_world: World) -> None:
    """A7: the second tap answers "already decided"."""
    user = await _student(auth_world, {})
    await auth_world.auth.offer_mcp_scopes.execute()
    token = _token(auth_world)
    decide = auth_world.auth.decide_scope_offer

    await decide.execute(token, user.id, grant=True)
    audits = len(auth_world.store.audits)
    again = await decide.execute(token, user.id, grant=False)

    assert again.result == DecideResult.ALREADY_DECIDED
    assert len(auth_world.store.audits) == audits
    [offer] = auth_world.store.scope_offers.values()
    assert offer.status == "granted"


async def test_decline_is_kept_and_never_offered_again(auth_world: World) -> None:
    """A7: a declined release is not offered again; no connector changes."""
    user = await _student(auth_world, {})
    await auth_world.auth.offer_mcp_scopes.execute()

    outcome = await auth_world.auth.decide_scope_offer.execute(
        _token(auth_world), user.id, grant=False
    )

    assert outcome.result == DecideResult.DECLINED
    [connector] = auth_world.store.connectors.values()
    assert connector.scopes == sorted(ALREADY)
    assert await auth_world.auth.offer_mcp_scopes.execute() == 0


async def test_forged_token_and_another_users_token_look_the_same(
    auth_world: World,
) -> None:
    """A7: another person's button reveals nothing and changes nothing."""
    owner = await _student(auth_world, {})
    other = await _student(auth_world)
    await auth_world.auth.offer_mcp_scopes.execute()
    decide = auth_world.auth.decide_scope_offer

    forged = await decide.execute("A" * 22, owner.id, grant=True)
    stolen = await decide.execute(_token(auth_world), other.id, grant=True)

    assert forged.result == stolen.result == DecideResult.NOT_AVAILABLE
    assert forged == stolen
    [offer] = auth_world.store.scope_offers.values()
    assert offer.status == "pending"


async def test_expired_offer_grants_nothing(auth_world: World) -> None:
    """A7: 14 days; the boundary itself is already expired."""
    user = await _student(auth_world, {})
    await auth_world.auth.offer_mcp_scopes.execute()
    token = _token(auth_world)
    auth_world.clock.advance(days=14)

    outcome = await auth_world.auth.decide_scope_offer.execute(
        token, user.id, grant=True
    )

    assert outcome.result == DecideResult.EXPIRED
    [connector] = auth_world.store.connectors.values()
    assert connector.scopes == sorted(ALREADY)


async def test_the_job_closes_expired_offers_and_keeps_them(auth_world: World) -> None:
    """A7: an expired offer is marked and its release is not offered again."""
    await _student(auth_world, {})
    await auth_world.auth.offer_mcp_scopes.execute()
    auth_world.clock.advance(days=15)

    assert await auth_world.auth.offer_mcp_scopes.execute() == 0

    [offer] = auth_world.store.scope_offers.values()
    assert offer.status == "expired"


async def test_snapshot_only_revoked_and_new_connectors_are_untouched(
    auth_world: World,
) -> None:
    """A7: a key revoked meanwhile stays revoked; a later key keeps its own picks."""
    user = await _student(auth_world, {"name": "Going"}, {"name": "Stays"})
    await auth_world.auth.offer_mcp_scopes.execute()
    by_name = {c.name: c for c in auth_world.store.connectors.values()}
    by_name["Going"].revoked_at = auth_world.clock.now()
    later = _connector(user, name="Later")
    auth_world.store.connectors[later.id] = later

    outcome = await auth_world.auth.decide_scope_offer.execute(
        _token(auth_world), user.id, grant=True
    )

    assert outcome.connector_names == ("Stays",)
    assert by_name["Going"].scopes == sorted(ALREADY)
    assert by_name["Going"].revoked_at is not None
    assert auth_world.store.connectors[later.id].scopes == sorted(ALREADY)


async def test_a_role_removed_meanwhile_grants_nothing(auth_world: World) -> None:
    """A7: the grant re-checks the role against the server."""
    user = await _student(auth_world, {})
    await auth_world.auth.offer_mcp_scopes.execute()
    auth_world.store.users[user.id].roles = {Role.TEACHER}

    outcome = await auth_world.auth.decide_scope_offer.execute(
        _token(auth_world), user.id, grant=True
    )

    assert outcome.connector_names == ()
    [connector] = auth_world.store.connectors.values()
    assert connector.scopes == sorted(ALREADY)


async def test_a_grant_drops_scopes_outside_the_catalog(auth_world: World) -> None:
    """A7: the grant re-validates the snapshot against the server's catalog."""
    user = await _student(auth_world, {})
    await auth_world.auth.offer_mcp_scopes.execute()
    [offer] = auth_world.store.scope_offers.values()
    auth_world.store.scope_offers[offer.id] = replace(
        offer, scopes=["sync:run", "people:read", "made:up"]
    )

    await auth_world.auth.decide_scope_offer.execute(
        _token(auth_world), user.id, grant=True
    )

    [connector] = auth_world.store.connectors.values()
    assert "sync:run" in connector.scopes
    assert "people:read" not in connector.scopes
    assert "made:up" not in connector.scopes


async def test_grant_clears_the_cached_overlay(auth_world: World) -> None:
    """A7: an OAuth client sees the new scopes at once, not after 30 seconds."""
    user = await _student(auth_world, {"token_hash": None, "hydra_client_id": "c"})
    [connector] = auth_world.store.connectors.values()
    key = f"mcp:overlay:{connector.id}"
    await auth_world.redis.set(key, "[]")
    await auth_world.auth.offer_mcp_scopes.execute()

    await auth_world.auth.decide_scope_offer.execute(
        _token(auth_world), user.id, grant=True
    )

    assert await auth_world.redis.get(key) is None


def _record(user_id: UUID, **fields: Any) -> McpCallRecord:
    base: dict[str, Any] = {
        "user_id": user_id,
        "connector_id": None,
        "client_id": None,
        "server": "student",
        "tool": "get_marks",
        "scope": "marks:read",
        "read_only": True,
        "outcome": "ok",
        "error_code": None,
        "error_id": None,
        "duration_ms": 3,
        "arguments": None,
        "result_summary": None,
        "ip": None,
    }
    return McpCallRecord(**{**base, **fields})


async def test_purge_removes_only_rows_older_than_90_days(auth_world: World) -> None:
    """B1: 90 days of retention, the boundary row stays."""
    user = await _student(auth_world)
    async with auth_world.uow() as uow:
        await uow.mcp_calls.add(_record(user.id, tool="old"))
        await uow.commit()
    auth_world.clock.advance(days=90)
    async with auth_world.uow() as uow:
        await uow.mcp_calls.add(_record(user.id, tool="edge"))
        await uow.commit()
    auth_world.clock.advance(seconds=1)

    removed = await auth_world.auth.purge_mcp_call_log.execute()

    assert removed == 1
    assert [row.tool for row in auth_world.store.mcp_calls] == ["edge"]


async def test_activity_is_scoped_to_the_actor_and_pages_by_cursor(
    auth_world: World,
) -> None:
    """B1: the user sees only their own calls, whatever the filter says."""
    user = await _student(auth_world)
    other = await _student(auth_world)
    other_connector = new_id()
    async with auth_world.uow() as uow:
        for index in range(3):
            await uow.mcp_calls.add(_record(user.id, tool=f"t{index}"))
            auth_world.clock.advance(seconds=1)
        await uow.mcp_calls.add(_record(other.id, connector_id=other_connector))
        await uow.commit()
    activity = auth_world.auth.list_mcp_activity

    first = await activity.for_user(user.id, limit=2)
    second = await activity.for_user(user.id, cursor=first.next_cursor, limit=2)
    stolen = await activity.for_user(user.id, connector_id=other_connector)

    assert [row.tool for row in first.items] == ["t2", "t1"]
    assert [row.tool for row in second.items] == ["t0"]
    assert second.next_cursor is None
    assert stolen.items == []


async def test_the_web_lists_only_my_open_offers_without_a_token(
    auth_world: World,
) -> None:
    """A7: pending and unexpired, mine, with read and write scopes and key names."""
    me = await _student(auth_world, {"name": "Claude"})
    other = await _student(auth_world, {"name": "Cursor"})
    await auth_world.auth.offer_mcp_scopes.execute()

    [offer] = await auth_world.auth.list_scope_offers.execute(me.id)

    assert offer.connector_names == ("Claude",)
    assert "sync:run" in offer.write_scopes
    assert not set(offer.read_scopes) & set(offer.write_scopes)
    assert not hasattr(offer, "token")
    assert len(await auth_world.auth.list_scope_offers.execute(other.id)) == 1

    await auth_world.auth.decide_scope_offer.decide_by_id(offer.id, me.id, grant=False)
    assert await auth_world.auth.list_scope_offers.execute(me.id) == []


async def test_a_web_decision_follows_the_same_rules(auth_world: World) -> None:
    """A7: a stranger learns nothing, the grant widens, a replay changes nothing."""
    me = await _student(auth_world, {"name": "Claude"})
    stranger = await _student(auth_world)
    await auth_world.auth.offer_mcp_scopes.execute()
    [offer] = await auth_world.auth.list_scope_offers.execute(me.id)
    decide = auth_world.auth.decide_scope_offer.decide_by_id

    foreign = await decide(offer.id, stranger.id, grant=True)
    unknown = await decide(new_id(), me.id, grant=True)
    granted = await decide(offer.id, me.id, grant=True)
    replay = await decide(offer.id, me.id, grant=False)

    assert foreign.result is DecideResult.NOT_AVAILABLE
    assert unknown.result is DecideResult.NOT_AVAILABLE
    assert granted.result is DecideResult.GRANTED
    assert granted.connector_names == ("Claude",)
    assert replay.result is DecideResult.ALREADY_DECIDED
    events = [
        e for e in auth_world.store.audits if e.type == "connector.scopes_extended"
    ]
    assert [e.metadata["via"] for e in events if e.metadata] == ["web"]


async def test_an_expired_offer_cannot_be_decided_on_the_web(
    auth_world: World,
) -> None:
    """A7: the date decides, even before the daily job closes the offer."""
    me = await _student(auth_world, {"name": "Claude"})
    await auth_world.auth.offer_mcp_scopes.execute()
    [offer] = await auth_world.auth.list_scope_offers.execute(me.id)
    auth_world.store.scope_offers[offer.id].expires_at = auth_world.clock.now()

    assert await auth_world.auth.list_scope_offers.execute(me.id) == []
    late = await auth_world.auth.decide_scope_offer.decide_by_id(
        offer.id, me.id, grant=True
    )
    assert late.result is DecideResult.EXPIRED


async def test_purge_honours_the_configured_retention_days(auth_world: World) -> None:
    """B1: a shorter retention removes what the default of 90 days would keep."""
    user = await _student(auth_world)
    async with auth_world.uow() as uow:
        await uow.mcp_calls.add(_record(user.id, tool="old"))
        await uow.commit()
    auth_world.clock.advance(days=7)
    async with auth_world.uow() as uow:
        await uow.mcp_calls.add(_record(user.id, tool="edge"))
        await uow.commit()
    auth_world.clock.advance(seconds=1)
    default = auth_world.auth.purge_mcp_call_log

    assert await default.execute() == 0
    assert await replace(default, retention_days=7).execute() == 1
    assert [row.tool for row in auth_world.store.mcp_calls] == ["edge"]
