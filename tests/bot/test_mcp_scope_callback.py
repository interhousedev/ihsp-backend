"""A7: the permission buttons: forged, replayed and foreign callbacks change nothing."""

from datetime import timedelta

from app.modules.identity.domain.connector import McpConnector
from app.modules.identity.domain.scope_offer import (
    OFFER_STATUS_PENDING,
    ScopeOffer,
    hash_offer_token,
)
from app.shared.contracts.callbacks import McpScopeCb
from app.shared.ids import new_id, random_token
from app.shared.mcp_scopes import RELEASE_2026_11
from tests.bot.support.fakes import STUDENT_TG, TEACHER_TG
from tests.bot.support.harness import Harness
from tests.bot.support.recording_bot import callback_update
from tests.identity.support import make_user

import pytest

UNLINKED = 7777


@pytest.fixture
def offer(harness: Harness) -> tuple[str, McpConnector]:
    """A pending offer of the linked student, with one token connector."""
    world = harness.world
    connector = McpConnector(
        id=new_id(),
        user_id=world.student.id,
        name="Claude",
        server="student",
        scopes=["marks:read"],
        token_hash="hash",
    )
    world.identity_store.connectors[connector.id] = connector
    token = random_token(16)
    row = ScopeOffer(
        id=new_id(),
        user_id=world.student.id,
        release_id=RELEASE_2026_11,
        scopes=["sync:run", "teachers:read"],
        connector_ids=[connector.id],
        status=OFFER_STATUS_PENDING,
        token_hash=hash_offer_token(token),
        expires_at=world.clock.now() + timedelta(days=14),
    )
    world.identity_store.scope_offers[row.id] = row
    world.identity_store.users[world.student.id] = make_user(id=world.student.id)
    return token, connector


def _status(harness: Harness) -> str:
    [row] = harness.world.identity_store.scope_offers.values()
    return row.status


def _scopes(harness: Harness, connector: McpConnector) -> list[str]:
    return harness.world.identity_store.connectors[connector.id].scopes


async def test_give_permissions(
    harness: Harness, offer: tuple[str, McpConnector]
) -> None:
    """A7: the owner's tap widens the key and offers a link to undo it."""
    token, connector = offer

    await harness.press(McpScopeCb(t=token, d="g").pack())

    assert _status(harness) == "granted"
    assert set(_scopes(harness, connector)) == {
        "marks:read",
        "sync:run",
        "teachers:read",
    }
    assert "mcp-offer-granted" in harness.last_text()
    assert harness.last_buttons()[0][0].url == "http://localhost:3001/connectors/"


async def test_dont_give_permissions(
    harness: Harness, offer: tuple[str, McpConnector]
) -> None:
    """A7: the owner's refusal changes no key."""
    token, connector = offer

    await harness.press(McpScopeCb(t=token, d="n").pack())

    assert _status(harness) == "declined"
    assert _scopes(harness, connector) == ["marks:read"]
    assert "mcp-offer-declined" in harness.last_text()


async def test_replay_only_says_already_decided(
    harness: Harness, offer: tuple[str, McpConnector]
) -> None:
    """A7: a second tap cannot turn a refusal into a grant."""
    token, connector = offer

    await harness.press(McpScopeCb(t=token, d="n").pack())
    await harness.press(McpScopeCb(t=token, d="g").pack())

    assert _status(harness) == "declined"
    assert _scopes(harness, connector) == ["marks:read"]
    assert harness.toasts[-1].text == "mcp-offer-already-decided"


async def test_forged_token(harness: Harness, offer: tuple[str, McpConnector]) -> None:
    """A7: an unknown token gets a generic answer."""
    _, connector = offer

    await harness.press(McpScopeCb(t="A" * 22, d="g").pack())

    assert _status(harness) == "pending"
    assert _scopes(harness, connector) == ["marks:read"]
    assert harness.toasts[-1].text == "mcp-offer-not-available"
    assert harness.edits == []


async def test_forged_decision_letter(
    harness: Harness, offer: tuple[str, McpConnector]
) -> None:
    """A7: only "g" grants, and only "g" or "n" decides anything."""
    token, connector = offer

    await harness.press(McpScopeCb(t=token, d="x").pack())

    assert _status(harness) == "pending"
    assert _scopes(harness, connector) == ["marks:read"]
    assert harness.toasts[-1].text == "mcp-offer-not-available"


@pytest.mark.parametrize("presser", [TEACHER_TG, UNLINKED])
async def test_another_users_callback(
    harness: Harness, offer: tuple[str, McpConnector], presser: int
) -> None:
    """A7: another linked person and a stranger get the same generic answer."""
    token, connector = offer

    await harness.press(McpScopeCb(t=token, d="g").pack(), user_id=presser)

    assert _status(harness) == "pending"
    assert _scopes(harness, connector) == ["marks:read"]
    assert harness.toasts[-1].text == "mcp-offer-not-available"
    assert harness.edits == []


async def test_the_button_works_in_a_private_chat_only(
    harness: Harness, offer: tuple[str, McpConnector]
) -> None:
    """A7: even the owner cannot decide from a group."""
    token, connector = offer
    update = callback_update(
        harness.bot, McpScopeCb(t=token, d="g").pack(), user_id=STUDENT_TG
    )
    assert update.callback_query is not None
    message = update.callback_query.message
    assert message is not None
    group = message.chat.model_copy(update={"id": -100, "type": "group"})
    query = update.callback_query.model_copy(
        update={"message": message.model_copy(update={"chat": group})}
    )
    update = update.model_copy(update={"callback_query": query})

    await harness.dp.feed_update(harness.bot, update, container=harness.world.container)

    assert _status(harness) == "pending"
    assert _scopes(harness, connector) == ["marks:read"]


async def test_expired_offer(harness: Harness, offer: tuple[str, McpConnector]) -> None:
    """A7: after 14 days the button only says so."""
    token, connector = offer
    harness.world.clock.advance(days=15)

    await harness.press(McpScopeCb(t=token, d="g").pack())

    assert _scopes(harness, connector) == ["marks:read"]
    assert harness.toasts[-1].text == "mcp-offer-expired"


def test_the_longest_callback_fits_telegram() -> None:
    """BOT-2: 64 bytes."""
    packed = McpScopeCb(t=random_token(16), d="g").pack()
    assert len(packed.encode()) <= 64
