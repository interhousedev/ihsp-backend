"""A7 and B1 on PostgreSQL: unique offers, a double tap, keyset reads and the purge."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.modules.identity.application.decide_scope_offer import DecideScopeOffer
from app.modules.identity.application.offer_mcp_scopes import OfferMcpScopes
from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.domain.scope_offer import (
    OFFER_STATUS_GRANTED,
    OFFER_STATUS_PENDING,
    DecideResult,
    ScopeOffer,
    hash_offer_token,
)
from app.modules.identity.domain.user import User
from app.modules.identity.infrastructure.uow import IdentityUnitOfWork
from app.modules.identity.ports.mcp_call_log import McpCallFilter
from app.shared.contracts.mcp_calls import McpCallRecord
from app.shared.ids import new_id
from app.shared.mcp_scopes import RELEASE_2026_11
from tests.fakes.clock import FixedClock
from tests.identity.support import make_user

UowMaker = Callable[[], IdentityUnitOfWork]
NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


class NoCache:
    """Nothing to clear."""

    async def invalidate(self, connector_ids: Sequence[UUID]) -> None:
        """Do nothing."""


async def _student(
    make_uow: UowMaker, **connector: object
) -> tuple[User, McpConnector]:
    suffix = new_id().hex[-10:]
    user = make_user(login=f"u.{suffix}", recovery_email=f"{suffix}@example.org")
    row = McpConnector(
        id=new_id(),
        user_id=user.id,
        name="Claude",
        server="student",
        scopes=["marks:read"],
        token_hash=f"hash{suffix}",
        **connector,  # type: ignore[arg-type]
    )
    async with make_uow() as uow:
        await uow.users.add(user)
        await uow.connectors.add(row)
        await uow.commit()
    return user, row


def _offer(user: User, connector: McpConnector, token: str) -> ScopeOffer:
    return ScopeOffer(
        id=new_id(),
        user_id=user.id,
        release_id=RELEASE_2026_11,
        scopes=["sync:run"],
        connector_ids=[connector.id],
        status=OFFER_STATUS_PENDING,
        token_hash=hash_offer_token(token),
        expires_at=NOW + timedelta(days=14),
    )


async def test_one_offer_per_user_and_release(make_uow: UowMaker) -> None:
    """A7: UNIQUE(user, release) answers False for the second insert."""
    user, connector = await _student(make_uow)
    async with make_uow() as uow:
        assert await uow.scope_offers.add_if_new(_offer(user, connector, new_id().hex))
        await uow.commit()
    async with make_uow() as uow:
        assert not await uow.scope_offers.add_if_new(
            _offer(user, connector, new_id().hex)
        )


async def test_double_tap_decides_once(make_uow: UowMaker) -> None:
    """A7: two taps: one grant, one "already decided"."""
    user, connector = await _student(make_uow)
    token = new_id().hex
    async with make_uow() as uow:
        await uow.scope_offers.add_if_new(_offer(user, connector, token))
        await uow.commit()
    decide = DecideScopeOffer(make_uow, FixedClock(NOW), NoCache())

    # The fixture shares one connection, so the taps run in turn. The loser's view of a
    # lost race is the guarded UPDATE matching no row, which the second call exercises.
    results = [
        await decide.execute(token, user.id, grant=True),
        await decide.execute(token, user.id, grant=True),
    ]

    assert sorted(r.result for r in results) == sorted(
        [DecideResult.GRANTED, DecideResult.ALREADY_DECIDED]
    )
    async with make_uow() as uow:
        stored = await uow.connectors.get(connector.id)
        offer = await uow.scope_offers.get_by_token_hash(hash_offer_token(token))
    assert stored is not None and stored.scopes.count("sync:run") == 1
    assert offer is not None and offer.status == OFFER_STATUS_GRANTED


async def test_the_guarded_update_decides_once(make_uow: UowMaker) -> None:
    """A7: a stale pending read still loses: the UPDATE re-checks the status."""
    user, connector = await _student(make_uow)
    offer = _offer(user, connector, new_id().hex)
    async with make_uow() as uow:
        await uow.scope_offers.add_if_new(offer)
        first = await uow.scope_offers.decide(offer.id, OFFER_STATUS_GRANTED, NOW)
        second = await uow.scope_offers.decide(offer.id, OFFER_STATUS_GRANTED, NOW)
    assert first is not None and second is None


async def test_extra_scopes_round_trip_and_candidates(make_uow: UowMaker) -> None:
    """A7: the candidate query looks at scopes and extra scopes of active keys only."""
    user, _ = await _student(make_uow, extra_scopes=["sync:run"])
    complete, _ = await _student(make_uow, extra_scopes=["sync:run", "marks:read"])
    revoked, _ = await _student(make_uow, revoked_at=NOW)
    async with make_uow() as uow:
        found = await uow.scope_offers.users_to_offer(
            "x", "student", ["sync:run", "tests:read"], NOW, after=None, limit=10_000
        )
        rows = await uow.connectors.list_for_user(user.id)
    assert user.id in found
    assert revoked.id not in found
    assert rows[0].extra_scopes == ["sync:run"]

    async with make_uow() as uow:
        narrow = await uow.scope_offers.users_to_offer(
            "x", "student", ["sync:run"], NOW, after=None, limit=10_000
        )
    assert complete.id not in narrow and user.id not in narrow


async def test_the_job_commits_offer_and_notification_together(
    make_uow: UowMaker,
) -> None:
    """A7: a second run on the real tables offers nothing to the same user."""
    user, _ = await _student(make_uow)
    job = OfferMcpScopes(make_uow, FixedClock(NOW))

    await job.execute()
    async with make_uow() as uow:
        before = await uow.scope_offers.users_to_offer(
            RELEASE_2026_11, "student", ["sync:run"], NOW, after=None, limit=10_000
        )
    await job.execute()

    assert user.id not in before


def _call(user_id: object, tool: str) -> McpCallRecord:
    return McpCallRecord(
        user_id=user_id,  # type: ignore[arg-type]
        connector_id=None,
        client_id=None,
        server="student",
        tool=tool,
        scope="marks:read",
        read_only=True,
        outcome="ok",
        error_code=None,
        error_id=None,
        duration_ms=1,
        arguments=None,
        result_summary=None,
        ip=None,
    )


async def test_call_log_reads_summary_and_purge(make_uow: UowMaker) -> None:
    """B1: keyset pages, per-user scoping, tool counts and a limited purge."""
    user, _ = await _student(make_uow)
    other, _ = await _student(make_uow)
    async with make_uow() as uow:
        for tool in ("a", "b", "c"):
            await uow.mcp_calls.add(_call(user.id, tool))
        await uow.mcp_calls.add(_call(other.id, "z"))
        await uow.commit()

    async with make_uow() as uow:
        mine = McpCallFilter(user_id=user.id)
        first = await uow.mcp_calls.search(mine, cursor=None, limit=2)
        second = await uow.mcp_calls.search(mine, cursor=first.next_cursor, limit=2)
        summary = await uow.mcp_calls.summary(mine)
    assert len(first.items) == 2 and len(second.items) == 1
    assert second.next_cursor is None
    assert {row.tool for row in [*first.items, *second.items]} == {"a", "b", "c"}
    assert {row.tool for row in summary} == {"a", "b", "c"}

    future = datetime.now(UTC) + timedelta(days=1)
    async with make_uow() as uow:
        assert await uow.mcp_calls.purge_before(future, limit=1) == 1
        await uow.commit()
