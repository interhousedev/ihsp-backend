"""Shares of guest bot answers (`g-{token}`), kept in Redis for seven days."""

from datetime import timedelta

from app.modules.links.domain.errors import LinkNotFoundError, ShareNotAllowedError
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


async def test_store_and_read_roundtrip(world: LinksWorld, clock: FixedClock) -> None:
    url = await world.services.share_guest_answer.execute(
        telegram_user_id=42, text=f"Marks:\n{BLOCK}{BAD}"
    )
    slug = url.rsplit("/", 1)[1]
    assert slug.startswith("g-")
    assert len(slug) == 2 + 32
    page = await world.services.get_public_message.execute(slug, ip=IP)
    assert "Table(" in page.text
    assert "Nope" not in page.text
    assert page.created_at == clock.now()
    assert page.expires_at == clock.now() + timedelta(days=7)


async def test_answer_without_valid_blocks_is_refused(world: LinksWorld) -> None:
    with pytest.raises(ShareNotAllowedError):
        await world.services.share_guest_answer.execute(
            telegram_user_id=42, text=f"Plain\n{BAD}"
        )


@pytest.mark.parametrize("slug", ["g-" + "0" * 32, "g-short", "g-" + "z" * 32, "g-"])
async def test_unknown_guest_slug_is_404(world: LinksWorld, slug: str) -> None:
    with pytest.raises(LinkNotFoundError):
        await world.services.get_public_message.execute(slug, ip=IP)
