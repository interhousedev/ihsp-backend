"""Shares of one bot answer with OpenUI blocks ("See visualization")."""

from dataclasses import fields
from uuid import UUID

from app.modules.links.application.views import PublicMessageView
from app.modules.links.domain.errors import (
    LinkGoneError,
    LinkNotFoundError,
    ShareNotAllowedError,
)
from app.modules.links.domain.link import LinkKind
from app.shared.actor import Actor
from tests.fakes.clock import FixedClock
from tests.fakes.links.world import LinksWorld

import pytest

IP = "203.0.113.7"
BLOCK = (
    "```openui\n"
    "root = Stack([t])\n"
    't = Table(["Day", "Mark"], [["Mon", 5], ["Tue", 4]])\n'
    "```\n"
)
BAD = "```openui\nroot = Nope(1)\n```\n"


def _chat(world: LinksWorld, answer: str) -> tuple[Actor, UUID]:
    ann = world.person("Ann")
    chat = world.ai.add_chat(
        ann.user_id, [("user", "My marks?"), ("assistant", answer)]
    )
    return ann, chat


async def test_share_lasts_seven_days_then_is_gone(
    world: LinksWorld, clock: FixedClock
) -> None:
    ann, chat = _chat(world, f"Your marks:\n{BLOCK}")
    view = await world.services.share_message.execute(ann, chat_id=chat, seq=2)

    assert view.link.kind is LinkKind.MESSAGE
    assert view.link.slug.startswith("m-") and len(view.link.slug) > 30
    assert view.url.endswith(f"/ai/{view.link.slug}")
    page = await world.services.get_public_message.execute(view.link.slug, ip=IP)
    assert "Your marks:" in page.text and "Table(" in page.text

    clock.advance(days=7, seconds=1)
    with pytest.raises(LinkGoneError):
        await world.services.get_public_message.execute(view.link.slug, ip=IP)
    mine = await world.services.list_my_links.execute(ann, kind=LinkKind.MESSAGE)
    assert [item.link.id for item in mine.items] == [view.link.id]


async def test_revoked_share_is_404(world: LinksWorld) -> None:
    ann, chat = _chat(world, BLOCK)
    view = await world.services.share_message.execute(ann, chat_id=chat, seq=2)

    await world.services.revoke_link.execute(ann, view.link.id)

    with pytest.raises(LinkNotFoundError):
        await world.services.get_public_message.execute(view.link.slug, ip=IP)


async def test_only_the_owner_can_share(world: LinksWorld) -> None:
    _, chat = _chat(world, BLOCK)
    bob = world.person("Bob")

    with pytest.raises(ShareNotAllowedError):
        await world.services.share_message.execute(bob, chat_id=chat, seq=2)


async def test_answers_without_valid_blocks_and_questions_are_refused(
    world: LinksWorld,
) -> None:
    ann, chat = _chat(world, f"Plain text\n{BAD}")

    with pytest.raises(ShareNotAllowedError):
        await world.services.share_message.execute(ann, chat_id=chat, seq=2)
    with pytest.raises(ShareNotAllowedError):
        await world.services.share_message.execute(ann, chat_id=chat, seq=1)


async def test_public_payload_has_only_text_and_dates(world: LinksWorld) -> None:
    ann, chat = _chat(world, f"Look\n{BLOCK}{BAD}")
    view = await world.services.share_message.execute(ann, chat_id=chat, seq=2)

    page = await world.services.get_public_message.execute(view.link.slug, ip=IP)

    assert {f.name for f in fields(PublicMessageView)} == {
        "text",
        "created_at",
        "expires_at",
    }
    assert "Nope(" not in page.text  # re-validated on read
    assert "Ann" not in page.text


async def test_other_share_slugs_are_not_messages(world: LinksWorld) -> None:
    with pytest.raises(LinkNotFoundError):
        await world.services.get_public_message.execute("c-unknown", ip=IP)
